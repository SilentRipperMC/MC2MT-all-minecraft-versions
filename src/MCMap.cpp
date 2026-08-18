#include "MCMap.hpp"
#include "util.hpp"
#include "modern.hpp"

#include "nbt/nbt.hpp"
#include "nbt/serialization.hpp"
#include "nbt/compression.hpp"
#include "Map.hpp"

#include <algorithm>
#include <climits>
#include <cstring>
#include <fstream>
#include <iostream>
#include <csignal>
#include <filesystem>


#define CHUNK_OFS_POS(x, z) ((x & 0x1F) + (z & 0x1F) * 32) * 4


MCMap::MCMap(const std::string & path) :
	path(path)
{
	std::ifstream f(path + "/level.dat",
			std::ios::in | std::ios::binary);
	std::string data;
	char buf[4096];
	while (f.read(buf, sizeof(buf)))
		data.append(buf, f.gcount());
	if (f.gcount() > 0)
		data.append(buf, f.gcount());
	std::string decomp;
	if (!NBT::decompress(&decomp, data.data(), data.size())) {
		std::cerr << decomp << std::endl;
		return;
	}
	meta.read(reinterpret_cast<const NBT::UByte *>(decomp.data()));
	// Detect a post-flattening (1.13+, DataVersion >= 1500) world so we can
	// read modern block_states sections directly instead of legacy Blocks.
	// Note: read() wraps the root compound under the empty-string key.
	{
		const NBT::Compound & data = meta[""]["Data"];
		auto it = data.find("DataVersion");
		if (it != data.end())
			modern_enabled = it->second.as<NBT::Int>() >= 1500;
	}
	//std::cerr << "Level data: " << meta[""]["Data"].dump() << std::endl;
}


void MCMap::listGroups(std::vector<MCGroup*> & v)
{
	MCFormat format = MCFormat::Regions;
	for (const auto &entry : std::filesystem::directory_iterator(path + "/region")) {
		std::string filename = entry.path().filename().string();
		Tokenizer tok(filename);

		std::string x_s, z_s, ext;
		if (!tok.next(&ext, '.') || ext != "r") continue;
		if (!tok.next(&x_s, '.')) continue;
		if (!tok.next(&z_s, '.')) continue;
		if (!tok.next(&ext, '.')) continue;
		if (tok.next(&ext, '.')) continue;

		MCFormat this_format;
		if (ext == "mca") this_format = MCFormat::Anvil;
		else if (ext == "mcr") this_format = MCFormat::Regions;
		else continue;

		// Select latest format found
		if (this_format > format) {
			format = this_format;
			v.clear();
		} else if (this_format != format) {
			continue;
		}

		int32_t x = std::stoi(x_s), z = std::stoi(z_s);
		int32_t x_nodes = x * 32 * MAP_BLOCK_SIZE;
		int32_t z_nodes = z * 32 * MAP_BLOCK_SIZE;

		if (x_nodes > MAX_DISTANCE || x_nodes < -MAX_DISTANCE ||
				z_nodes > MAX_DISTANCE || z_nodes < -MAX_DISTANCE) {
			std::cerr << "Skiping group (" << x << ", " << z
					<< ") (Too far from origin)" << std::endl;
			continue;
		}

		v.push_back(new MCGroup(filename, x, z, format));
	}
}


void MCMap::listChunks(MCGroup * gid, MCChunkList * blocks)
{
	assert(gid->f == nullptr);

	gid->f = new std::ifstream(path + "/region/" +
		gid->name, std::ios::in | std::ios::binary);

	int32_t chunk_x = gid->x * 32,
		chunk_z = gid->z * 32;

	const char tmp_nul[3] = {0};
	char tmp[3];
	for (int32_t cx = chunk_x; cx < chunk_x + 32; ++cx)
	for (int32_t cz = chunk_z; cz < chunk_z + 32; ++cz) {
		gid->f->seekg(CHUNK_OFS_POS(cx, cz));
		gid->f->read(tmp, 3);
		if (memcmp(tmp, tmp_nul, 3) != 0) {
			blocks->push_back(MCChunkPos {cx, cz});
		}
	}
}


bool MCMap::loadChunk(MCChunk * chunk, const MCGroup & gid, MCChunkPos cp)
{
	assert(gid.f != nullptr);
	return readChunk(chunk, gid.f, cp, gid.format);
}


bool MCMap::readChunkData(std::ifstream * f, MCChunkPos cp, std::string &data)
{
	char tmp[4] = {0};
	std::streamoff ofs = CHUNK_OFS_POS(cp.x, cp.z);

	f->seekg(ofs);
	f->read(tmp+1, 3);
	// Offset in 4KiB sectors
	ofs = NBT::readInt(reinterpret_cast<const NBT::UByte *>(tmp)) << 12;
	if (ofs == 0)  // This chunk wasn't saved.
		return false;

	// Length in 4KiB sectors (rounded up)
	f->read(tmp, 1);
	uint16_t length_sectors = tmp[0];
	assert(length_sectors != 0);

	f->seekg(ofs);

	f->read(tmp, 4);
	uint32_t length = NBT::readInt(reinterpret_cast<const NBT::UByte *>(tmp));

	// This should be true, but sometimes it isn't...
	if ((length + 4) > ((uint32_t)length_sectors << 12)) {
		std::cerr << "WARNING: Chunk length mismatch.  "
			"length_sectors=" << length_sectors
			<< " length=" << length << std::endl;
	}

	f->read(tmp, 1);
	uint8_t compression_type = static_cast<uint8_t>(tmp[0]);

	// Only GZip and Zlib compression are specified, and in practice only ZLib is used
	if (compression_type > 2) {
		std::cerr << "WARNING: Ignoring chunk with unknown compression type." << std::endl;
		return false;
	}

	std::string compressed;
	compressed.resize(length - 1);
	f->read(&compressed[0], length - 1);

	NBT::decompress(&data, compressed.data(), compressed.size());
	return true;
}


static int modern_bits_for_palette(int palette_size)
{
	if (palette_size <= 1)
		return 0;
	int bits = 0;
	int n = palette_size - 1;
	while (n > 0) {
		bits++;
		n >>= 1;
	}
	return bits < 4 ? 4 : bits;
}


// Extracts the i-th entry (i in 0..4095) from a packed long array.
// Since 20w17a (DataVersion 2529) each value fits inside a single long and
// never spans two longs: there are (64 / bits) values per long, packed
// least-significant-bit first, with the unused high bits left as padding.
static uint32_t modern_extract(const NBT::Long *longs, int bits, int i)
{
	int values_per_long = 64 / bits;
	int idx = i / values_per_long;
	int off = (i % values_per_long) * bits;
	uint64_t mask = (1ULL << bits) - 1ULL;
	return static_cast<uint32_t>(
			(static_cast<uint64_t>(longs[idx]) >> off) & mask);
}


// Returns a lookup (by exact name) for a value, or -1.
static int modern_prop_int(const NBT::Compound & props, const char *key)
{
	auto it = props.find(key);
	if (it == props.end())
		return -1;
	try {
		return std::stoi(it->second.as<std::string>());
	} catch (...) {
		return -1;
	}
}

// MC color name (e.g. "light_gray", "red") -> Mineclonia candle
// palette_index (param2).  Order matches mcl_dyes palette.
static uint8_t candle_palette_index(const std::string &mc_color)
{
	static const std::map<std::string, uint8_t> m = {
		{"white", 0}, {"light_gray", 1}, {"gray", 2}, {"black", 3},
		{"purple", 4}, {"blue", 5}, {"light_blue", 6}, {"cyan", 7},
		{"green", 8}, {"lime", 9}, {"yellow", 10}, {"brown", 11},
		{"orange", 12}, {"red", 13}, {"magenta", 14}, {"pink", 15},
	};
	auto it = m.find(mc_color);
	return it == m.end() ? 0 : it->second;
}

// MC banner base-color index (white=0..black=15) for a banner block name
// like "red_banner" / "red_wall_banner".  -1 if the name is not a banner.
static int banner_base_color(const std::string &name)
{
	static const std::map<std::string, int> m = {
		{"white", 0}, {"orange", 1}, {"magenta", 2}, {"light_blue", 3},
		{"yellow", 4}, {"lime", 5}, {"pink", 6}, {"gray", 7},
		{"light_gray", 8}, {"cyan", 9}, {"purple", 10}, {"blue", 11},
		{"brown", 12}, {"green", 13}, {"red", 14}, {"black", 15},
	};
	std::string base = name;
	if (base.size() >= 11 &&
			base.compare(base.size() - 11, 11, "_wall_banner") == 0)
		base.resize(base.size() - 11);
	else if (base.size() >= 7 &&
			base.compare(base.size() - 7, 7, "_banner") == 0)
		base.resize(base.size() - 7);
	else
		return -1;
	auto it = m.find(base);
	return it == m.end() ? -1 : it->second;
}

// Parses a modern section's block_states into a list of namespace-stripped
// base names and 4096 palette indices in YZX order (i = y*256 + z*16 + x).
// node_data (may be null) receives a per-node value for the direct path:
//   candles       -> Mineclonia palette_index (param2)
//   banners       -> (base_color << 4) | state, where state is the MC
//                    rotation (standing) or the Mineclonia wallmounted
//                    param2 (hanging); the banner block-entity converter
//                    uses both halves.
static void parse_modern_section(const NBT::Tag &section,
		std::vector<std::string> &palette_names, uint16_t *indices,
		uint8_t *node_data)
{
	const NBT::Compound &sec = section;
	auto bs_it = sec.find("block_states");
	if (bs_it == sec.end()) {
		// Section without block_states: everything is air.
		palette_names.clear();
		palette_names.push_back("air");
		for (int i = 0; i < NODES_PER_BLOCK; ++i) {
			indices[i] = 0;
			if (node_data)
				node_data[i] = 0;
		}
		return;
	}
	const NBT::Compound &bs = bs_it->second;
	auto pit = bs.find("palette");
	if (pit == bs.end()) {
		// Fully empty section: everything is air.
		palette_names.clear();
		palette_names.push_back("air");
		for (int i = 0; i < NODES_PER_BLOCK; ++i) {
			indices[i] = 0;
			if (node_data)
				node_data[i] = 0;
		}
		return;
	}
	const NBT::List pal = pit->second;
	palette_names.clear();
	palette_names.reserve(pal.size);
	std::vector<uint8_t> pal_data(pal.size, 0);
	for (NBT::UInt i = 0; i < pal.size; ++i) {
		const NBT::Tag & entry = pal.value[i];
		std::string full = entry["Name"].as<std::string>();
		size_t colon = full.find(':');
		std::string name = colon == std::string::npos ?
				full : full.substr(colon + 1);
		try {
			const NBT::Compound & props = entry["Properties"];
			// Thread the door "half" block state through so doors map to
			// the correct Mineclonia half (_t_1 bottom / _t_2 top).
			// Trapdoors also carry a "half" state but use one node.
			if (name.size() >= 5 &&
					name.compare(name.size() - 5, 5, "_door") == 0) {
				auto hit = props.find("half");
				if (hit != props.end())
					name += "|" + hit->second.as<std::string>();
			}
			// Light block: MC `level` state (0-15) -> mcl_core:light_0..14.
			// Mineclonia stops at light_14 (core.LIGHT_MAX), so clamp 15.
			if (name == "light") {
				int lvl = modern_prop_int(props, "level");
				if (lvl < 0 || lvl > 14)
					lvl = 14;
				name += "|" + std::to_string(lvl);
			}
			// Beds: MC `part` state picks the half (head = pillow =
			// Mineclonia `_top`, foot = Mineclonia `_bottom`) and MC
			// `facing` becomes the facedir param2 (direction from the
			// foot to the head, same convention as the stairs).
			if (name.size() >= 4 &&
					name.compare(name.size() - 4, 4, "_bed") == 0) {
				auto pit = props.find("part");
				if (pit != props.end())
					name += "|" + pit->second.as<std::string>();
				std::string facing = "north";
				auto f_it = props.find("facing");
				if (f_it != props.end())
					facing = f_it->second.as<std::string>();
				int bidx;
				if (facing == "north") bidx = 0;
				else if (facing == "south") bidx = 2;
				else if (facing == "east") bidx = 1;
				else bidx = 3;  // west
				pal_data[i] = static_cast<uint8_t>(bidx);
			}
			// Stairs: MC `facing`/`half`/`shape` pick the Mineclonia node
			// (stair_x / _outer / _inner, threaded as |shape) and the
			// facedir param2.  The output world is N/S-mirrored, so the
			// riser direction swaps north<->south; the param2 index is the
			// riser direction (0=+Z, 1=+X, 2=-Z, 3=-X) and right-hand
			// corners (outer_right / inner_right) rotate +1 (mod 4).
			// half=top uses the ceiling encoding c(0)=20, c(1)=23,
			// c(2)=22, c(3)=21.
			if (name.size() >= 7 &&
					name.compare(name.size() - 7, 7, "_stairs") == 0) {
				std::string facing = "north";
				auto f_it = props.find("facing");
				if (f_it != props.end())
					facing = f_it->second.as<std::string>();
				int idx;
				if (facing == "north") idx = 0;
				else if (facing == "south") idx = 2;
				else if (facing == "east") idx = 1;
				else idx = 3;  // west
				std::string shape = "straight";
				auto s_it = props.find("shape");
				if (s_it != props.end())
					shape = s_it->second.as<std::string>();
				if (shape == "outer_right" || shape == "inner_right")
					idx = (idx + 1) & 3;
				bool top = false;
				auto h_it = props.find("half");
				if (h_it != props.end())
					top = h_it->second.as<std::string>() == "top";
				static const uint8_t ceil_p2[4] = {20, 23, 22, 21};
				uint8_t p2 = top ? ceil_p2[idx] :
						static_cast<uint8_t>(idx);
				// Corner stairs (inner/outer) on the top half need one
				// extra rotation in the ceiling encoding:
				// 20->21, 21->22, 22->23, 23->20.
				if (top && shape != "straight")
					p2 = static_cast<uint8_t>(((p2 - 20 + 1) % 4) + 20);
				pal_data[i] = p2;
				name += "|" + shape;
			}
			// Pointed dripstone: MC `vertical_direction` (up/down) picks
			// the Mineclonia family (bottom_* stalagmite / top_* stalactite)
			// and `thickness` (tip/frustum/middle/base) picks the stage.
			if (name == "pointed_dripstone") {
				auto d_it = props.find("vertical_direction");
				std::string dir = d_it == props.end() ?
						"" : d_it->second.as<std::string>();
				auto t_it = props.find("thickness");
				std::string thk = t_it == props.end() ?
						"" : t_it->second.as<std::string>();
				name += "|" + dir + "|" + thk;
			}
			// Candles: same node name for every color (color is param2);
			// the count (1-4) and lit state pick the node variant.
			bool is_cake = name.size() >= 12 &&
					name.compare(name.size() - 12, 12, "_candle_cake") == 0;
			bool is_candle = !is_cake && name.size() >= 7 &&
					name.compare(name.size() - 7, 7, "_candle") == 0;
			if (is_candle || is_cake) {
				size_t cut = name.size() - (is_cake ? 12 : 7);
				uint8_t p = candle_palette_index(name.substr(0, cut));
				int lit = 0;
				auto lit_it = props.find("lit");
				if (lit_it != props.end())
					lit = lit_it->second.as<std::string>() == "true" ? 1 : 0;
				if (is_cake) {
					if (lit)
						name += "|lit";
				} else {
					int n = modern_prop_int(props, "candles");
					if (n >= 1 && n <= 4)
						name += "|" + std::to_string(n);
					if (lit)
						name += "|lit";
				}
				pal_data[i] = p;
			}
			// Banners: color lives in the block name; the block-entity
			// converter reads (base_color << 4) | state from node_data.
			if (banner_base_color(name) >= 0) {
				uint8_t base = static_cast<uint8_t>(banner_base_color(name));
				uint8_t state = 0;
				if (name.size() >= 11 &&
						name.compare(name.size() - 11, 11, "_wall_banner") == 0) {
					// Hanging banner: param2 is wallmounted.  The output is
					// a 180-degree-rotated world, so MC facing maps to:
					// north->4 (Z-), south->5 (Z+), east->3 (X+), west->2 (X-).
					auto f_it = props.find("facing");
					std::string facing = f_it == props.end() ?
							"" : f_it->second.as<std::string>();
					if (facing == "north") state = 4;
					else if (facing == "south") state = 5;
					else if (facing == "east") state = 3;
					else if (facing == "west") state = 2;
					else state = 4;
				} else {
					// Standing banner: keep the MC rotation (0-15) for the
					// entity; the block-entity converter mirrors it.
					int r = modern_prop_int(props, "rotation");
					if (r >= 0 && r <= 15)
						state = static_cast<uint8_t>(r);
				}
				pal_data[i] = static_cast<uint8_t>((base << 4) | state);
			}
		} catch (...) {}
		palette_names.push_back(name);
	}

	int pal_size = static_cast<int>(palette_names.size());
	if (pal_size <= 1) {
		for (int i = 0; i < NODES_PER_BLOCK; ++i) {
			indices[i] = 0;
			if (node_data)
				node_data[i] = pal_data[0];
		}
		return;
	}

	auto dit = bs.find("data");
	if (dit == bs.end()) {
		// Multi-entry palette without a data array (unusual): use index 0.
		for (int i = 0; i < NODES_PER_BLOCK; ++i) {
			indices[i] = 0;
			if (node_data)
				node_data[i] = pal_data[0];
		}
		return;
	}
	const NBT::LongArray data = dit->second;
	int bits = modern_bits_for_palette(pal_size);
	for (int i = 0; i < NODES_PER_BLOCK; ++i) {
		indices[i] = static_cast<uint16_t>(
				modern_extract(data.value, bits, i));
		if (node_data)
			node_data[i] = pal_data[indices[i]];
	}
}


bool MCMap::readChunk(MCChunk * chunk, std::ifstream * f, MCChunkPos cp, MCFormat format)
{
	std::string data;
	if (!readChunkData(f, cp, data))
		return false;

	NBT::Tag nbt_data(reinterpret_cast<const NBT::UByte *>(data.data()));
	NBT::Tag & root = nbt_data[""];
	bool modern = false;
	{
		const NBT::Compound & rc = root;
		modern = rc.find("sections") != rc.end();
	}
	NBT::Tag & level = modern ? root : root["Level"];

	switch (format) {
	case MCFormat::Anvil: {
		const NBT::List secs = level[modern ? "sections" : "Sections"];
		for (uint32_t i = 0; i < secs.size; ++i) {
			NBT::Tag & sec = secs.value[i];
			if (modern) {
				int cy = static_cast<int>(sec["Y"].as<NBT::Byte>());
				int legacy_y = cy + modern_shift_sub;
				if (legacy_y < 0 ||
						legacy_y >= MC_MAP_HEIGHT / MAP_BLOCK_SIZE)
					continue;
				// Pass the chunk position straight through so the
				// MCBlock constructor applies the same X inversion as
				// the legacy path (pos.x = -cp.x - 1).
				chunk->push_back(new MCBlock(level, cp,
					static_cast<uint8_t>(legacy_y), format, sec, true));
			} else {
				chunk->push_back(new MCBlock(level, cp,
					sec["Y"].as<NBT::Byte>(), format, sec));
			}
		}
		break;
	}
	case MCFormat::Regions:
		for (unsigned y_slice = 0; y_slice < 8; ++y_slice) {
			chunk->push_back(new MCBlock(level, cp,
				y_slice, format));
		}
		break;
	}
	return true;
}


void MCMap::scanModern()
{
	std::vector<MCGroup*> groups;
	listGroups(groups);

	int min_y_block = INT_MAX;
	int max_y_block = INT_MIN;
	std::vector<std::string> palette_names;
	std::vector<uint16_t> indices(NODES_PER_BLOCK);

	for (MCGroup * g : groups) {
		MCChunkList chunks;
		listChunks(g, &chunks);
		for (const MCChunkPos & cp : chunks) {
			std::string data;
			if (!readChunkData(g->f, cp, data))
				continue;
			NBT::Tag nbt_data(reinterpret_cast<const NBT::UByte *>(data.data()));
			NBT::Tag & root = nbt_data[""];
			const NBT::Compound & rc = root;
			if (rc.find("sections") == rc.end())
				continue;
			const NBT::List secs = root["sections"];
			for (NBT::UInt i = 0; i < secs.size; ++i) {
				NBT::Tag & sec = secs.value[i];
				int cy = static_cast<int>(sec["Y"].as<NBT::Byte>());
				parse_modern_section(sec, palette_names, indices.data(),
						nullptr);
				for (const std::string & n : palette_names)
					modern_registry.add(n);

				int air_idx = -1;
				for (size_t j = 0; j < palette_names.size(); ++j) {
					const std::string & n = palette_names[j];
					if (n == "air" || n == "cave_air" || n == "void_air") {
						air_idx = static_cast<int>(j);
						break;
					}
				}
				if (air_idx < 0)
					continue;
				for (int k = 0; k < NODES_PER_BLOCK; ++k) {
					if (indices[k] != static_cast<uint16_t>(air_idx)) {
						int y_block = cy * 16 + (k >> 8);
						if (y_block < min_y_block)
							min_y_block = y_block;
						break;
					}
				}
				for (int k = NODES_PER_BLOCK - 1; k >= 0; --k) {
					if (indices[k] != static_cast<uint16_t>(air_idx)) {
						int y_block = cy * 16 + (k >> 8);
						if (y_block > max_y_block)
							max_y_block = y_block;
						break;
					}
				}
			}
		}
		delete g;
	}

	if (min_y_block < 0) {
		modern_shift_sub = (-min_y_block + 15) / 16;
		// A world built entirely below Y=0 (e.g. a house at Y -64..-1)
		// would end up buried underground in Luanti.  When there is no
		// content at or above Y=0, raise it so the bottom lands at
		// Luanti ground level (Y=0) instead of staying at MC depth.
		if (max_y_block < 0)
			modern_shift_sub += BLOCK_Y_OFFSET;
	} else {
		modern_shift_sub = 0;
	}

	modern_registry.finalize();
}


/***********
 * MCBlock *
 ***********/MCBlock::MCBlock(const NBT::Tag & chunk, MCChunkPos cp,
	 uint8_t y_slice, MCFormat format, const NBT::Tag &sec, bool modern)
	: direct_content(modern)
{
	switch (format) {
	case MCFormat::Anvil:
		if (modern) {
			// Direct 1.18+ conversion: the chunk positions are KEPT exactly
			// as they are (pos.x = -cp.x-1, pos.z = cp.z -- do not change),
			// and the content of each chunk is only X-mirrored within the
			// section (see fromModernSection()).  No 180-degree rotation of
			// the content: Z is left untouched, so the whole world is a
			// single coherent east/west reflection (output X = -MC X - 1)
			// with no rotation and no seams.
			pos = {-cp.x-1, y_slice, cp.z};
			fromModernSection(sec);
		} else {
			/* The X axis has to be inverted to convert to Minetest
			 * (the chunk location is at the L lower corner, so subtract
			 * one or there would be 2 chunks at 0).
			 */
			pos = {-cp.x-1, y_slice, cp.z};
			fromSection(sec);
		}
		break;
	case MCFormat::Regions:
		pos = {cp.x, y_slice, cp.z};
		// No luck, we have to convert
		fromChunk(chunk, y_slice);
		break;
	}
	if (modern) {
		// 1.18+ chunks store block entities in "block_entities" with
		// namespaced ids (e.g. "minecraft:banner").  Positions are
		// transformed the same way as the blocks: X untouched inside the
		// section, Z mirrored (dest z = 15 - src z), Y local to the
		// section.  The id keeps only its namespace-stripped part so the
		// legacy be_convert table applies.
		const NBT::Compound & chd = chunk;
		auto be_it = chd.find("block_entities");
		if (be_it != chd.end()) {
			const NBT::List & bes = be_it->second;
			int cy = y_slice - modern_shift_sub;
			for (unsigned i = 0; i < bes.size; ++i) {
				const NBT::Tag & te = bes.value[i];
				int32_t by = static_cast<int32_t>(te["y"]);
				if ((by >> 4) != cy)
					continue;
				NBT::Tag t(te);  // Copy
				int32_t bx = static_cast<int32_t>(te["x"]);
				int32_t bz = static_cast<int32_t>(te["z"]);
				t["x"] = bx & 0xF;
				t["y"] = (by & 0xF);
				t["z"] = 15 - (bz & 0xF);
				// Strip the "minecraft:" namespace from the id.
				std::string bid = te["id"].as<std::string>();
				size_t colon = bid.find(':');
				if (colon != std::string::npos)
					bid = bid.substr(colon + 1);
				t["id"] = bid;
				tile_entities.push_back(std::move(t));
			}
		}
		return;
	}
	NBT::List tentities = chunk["TileEntities"];
	for (unsigned i = 0; i < tentities.size; ++i) {
		const NBT::Tag te = tentities.value[i];
		if ((te["y"].as<NBT::Int>() >> 4) == y_slice) {
			NBT::Tag t(te);  // Copy
			// Entity data stores it's own position information,
			// so has to be modified independently in addition
			// to other blocks.
			t["y"] = (t["y"].as<NBT::Int>() & 0xF) - 16;
			// Within the chunk X position has to be inverted
			// to convert to Minetest.
			if (format == MCFormat::Anvil)
				t["x"] = pos.x * MAP_BLOCK_SIZE + (MAP_BLOCK_SIZE-1) -
					t["x"].as<NBT::Int>() % 16;
			tile_entities.push_back(std::move(t));
		}
	}
}

// Short for GET_NBT_RAW_BYTE_ARRAY
#define GNBTRBA(val) reinterpret_cast<const uint8_t *>((val).as<const NBT::ByteArray>().value)

void MCBlock::fromSection(const NBT::Tag & section)
{
	/* Anvil format is YZX ((y * 16 + z) * 16 + x).
	 * Block data is actually 16-bits per data point (i.e., per node),
	 * but is split into 8-bit 'blocks', 4-bit 'add' (added to blocks to
	 * obtain full block ID), and 4-bit 'data' (like MT's param2).
	 *
	 * To convert Minecraft to Minetest coordinates you must invert
	 * the X order while leaving Y and Z the same.
	 */
	const NBT::Compound & sec = section;

	reverseXAxis(blocks, GNBTRBA(sec.at("Blocks")));

	// "Add" array is optional
	auto it = sec.find("Add");
	if (it != sec.end()) {
		uint8_t blocks_add[NODES_PER_BLOCK];
		expandHalfBytes(blocks_add, GNBTRBA(it->second));

		for (size_t i = 0; i < NODES_PER_BLOCK; ++i) {
			blocks[i] |= static_cast<uint16_t>(blocks_add[i]) << 8;
		}
	}

	// Data, sky light, and block light are 4-bit
	expandHalfBytes(data,        GNBTRBA(sec.at("Data")));
	expandHalfBytes(sky_light,   GNBTRBA(sec.at("SkyLight")));
	expandHalfBytes(block_light, GNBTRBA(sec.at("BlockLight")));
}


void MCBlock::fromModernSection(const NBT::Tag & section)
{
	static thread_local std::vector<std::string> palette_names;
	static thread_local std::vector<uint16_t> indices;
	static thread_local std::vector<uint8_t> node_data;
	indices.resize(NODES_PER_BLOCK);
	node_data.resize(NODES_PER_BLOCK);
	parse_modern_section(section, palette_names, indices.data(),
			node_data.data());
	// The chunk positions are fixed (pos.x = -cp.x-1, pos.z = cp.z -- do
	// not change).  The content of each chunk is north/south mirrored
	// within the section only: a node at local (x, z) comes from source
	// (x, 15-z).  X (east/west) and Y are left untouched.
	for (uint16_t y = 0; y < MAP_BLOCK_SIZE; ++y)
	for (uint16_t z = 0; z < MAP_BLOCK_SIZE; ++z)
	for (uint16_t x = 0; x < MAP_BLOCK_SIZE; ++x) {
		uint16_t src = (y << 8) | ((MAP_BLOCK_SIZE - 1 - z) << 4) | x;
		uint16_t dst = (y << 8) | (z << 4) | x;
		blocks[dst] = modern_registry.lookup(palette_names[indices[src]]);
		data[dst] = node_data[src];
	}
	// Lighting is unused in direct mode (all zeros).  data[] carries
	// param2 for candles and banners.
	std::memset(sky_light, 0, sizeof(sky_light));
	std::memset(block_light, 0, sizeof(block_light));
}


void MCBlock::fromChunk(const NBT::Tag & chunk, uint8_t y_slice)
{
	extractSlice         (blocks,      GNBTRBA(chunk["Blocks"]),     y_slice);
	extractSliceHalfBytes(data,        GNBTRBA(chunk["Data"]),       y_slice);
	extractSliceHalfBytes(sky_light,   GNBTRBA(chunk["SkyLight"]),   y_slice);
	extractSliceHalfBytes(block_light, GNBTRBA(chunk["BlockLight"]), y_slice);
}


/// Reverses X axis node order within each slice.
void MCBlock::reverseXAxis(uint16_t * data, const uint8_t * l)
{
	uint16_t data_key = 0;
	for (uint16_t y = 0; y < MAP_BLOCK_SIZE; ++y)
	for (uint16_t z = 0; z < MAP_BLOCK_SIZE; ++z)
	for (uint16_t x = 0; x < MAP_BLOCK_SIZE; ++x) {
		uint16_t i = (y << 8) | (((MAP_BLOCK_SIZE-1) - z) << 4) | (x);
		data[data_key++] = l[i];
	}
}


/// Reverses X axis node order, and expands 4-bit sequences into 8-bit sequences.
void MCBlock::expandHalfBytes(uint8_t * data, const uint8_t * l)
{
	uint16_t data_key = 0;
	for (uint16_t y = 0; y < MAP_BLOCK_SIZE; ++y)
	for (uint16_t z = 0; z < MAP_BLOCK_SIZE; ++z)
	for (uint16_t x = 0; x < MAP_BLOCK_SIZE/2;  ++x) {
		int16_t i = (y << 7) | (((MAP_BLOCK_SIZE-1) - z) << 3) | x;
		uint8_t b = l[i];
		data[data_key++] = b & 0xF;
		data[data_key++] = (b >> 4) & 0xF;
	}
}


/// Changes order from XZY to YZX.
void MCBlock::extractSlice(uint16_t * data, const uint8_t * l, uint8_t y_slice)
{
	uint16_t key = y_slice << 4;
	uint16_t data_key = 0;
	// Change order from XZY to YZX
	for (uint8_t y = 0; y < MAP_BLOCK_SIZE; ++y) {
		for (uint8_t z = 0; z < MAP_BLOCK_SIZE; ++z) {
			for (uint8_t x = 0; x < MAP_BLOCK_SIZE; ++x) {
				data[data_key++] = l[key];
				key += 2048;
			}
			key = (key & 0x7FF) + 128;
		}
		key = (key & 0x7F) + 1;
	}
}


/// Changes order from XZY to YZX and expands 4-bit sequences into 8-bit sequences.
void MCBlock::extractSliceHalfBytes(uint8_t * data, const uint8_t * l,
		uint8_t y_slice)
{
	uint16_t key = y_slice << 3;
	uint16_t data_key_1 = 0;
	uint16_t data_key_2 = 256;  // One layer above the previous one
	// Change order from XZY to YZX
	for (uint8_t y = 0; y < MAP_BLOCK_SIZE; y += 2) {  // Two values of y at a time
		for (uint8_t z = 0; z < MAP_BLOCK_SIZE; ++z) {
			for (uint8_t x = 0; x < MAP_BLOCK_SIZE; ++x) {
				uint8_t b = l[key];
				data[data_key_1++] = b & 0xF;
				data[data_key_2++] = (b >> 4) & 0xF;
				key += 1024;
			}
			key = (key & 0x3FF) + 64;
		}
		key = (key & 0x3F) + 1;
		data_key_1 += BLOCK_YSTRIDE;  // Skip a layer
		data_key_2 += BLOCK_YSTRIDE;
	}
}
