#include "convert.hpp"
#include "util.hpp"
#include "MTMap.hpp"
#include <cassert>
#include <cstring>
#include <iostream>
#include <fstream>
#include <sstream>
#include <filesystem>

#define MC_ID_MAX 348
#define MC_DATA_MAX 15

static ConversionData conversion_table[MC_ID_MAX+1][MC_DATA_MAX+1] = {{{false, 0, CONTENT_IGNORE, nullptr}}};
static std::map<std::string, uint16_t> conversion_map;
static std::map<uint32_t, ConversionData> custom_conversion_map;

static uint32_t custom_key(uint16_t id, uint8_t data)
{
	return (static_cast<uint32_t>(id) << 8) | data;
}

static void add_conversion(uint16_t mc_id, const char *mc_name,
		const char *datas, const char *name, uint8_t param2, bool tool,
		ConversionCallback cb)
{
	assert(mc_id <= MC_ID_MAX);
	content_t cid = MTMap::getId(name);
	ConversionData cd {tool, param2, cid, cb};

	if (datas == nullptr) {
		for (uint16_t i = 0; i < MC_DATA_MAX+1; ++i) {
			conversion_table[mc_id][i] = cd;
		}
	} else {
		Tokenizer tok(datas);
		std::string data_str;
		while (tok.next(&data_str, ',')) {
			uint8_t data = std::stoi(data_str);
			assert(data <= MC_DATA_MAX);
			conversion_table[mc_id][data] = cd;
		}
	}
	conversion_map[mc_name] = mc_id;
}


bool get_conversion(const ConversionData **cd, uint16_t id, uint16_t data)
{
	if (data <= MC_DATA_MAX) {
		auto custom = custom_conversion_map.find(custom_key(id, data));
		if (custom != custom_conversion_map.end()) {
			*cd = &custom->second;
			return custom->second.cid != CONTENT_IGNORE;
		}
	}
	if (id > MC_ID_MAX)
		return false;
	const ConversionData *p;
	if (data <= MC_DATA_MAX) {
		p = &(conversion_table[id][data]);
	} else {
		p = &(conversion_table[id][0]);
		assert(p->cid == CONTENT_IGNORE || p->tool);
	}
	*cd = p;
	return p->cid != CONTENT_IGNORE;
}


bool get_conversion(const ConversionData **cd, const std::string &name, uint16_t data)
{
	auto it = conversion_map.find(name);
	if (it == conversion_map.end())
		return false;
	return get_conversion(cd, it->second, data);
}


// Updates lighting, particularly for nodebox nodes like stairs and slabs,
// which MC seems to always store with a light value of 0.
// This simply tries to grab a light value from the adjacent nodes.
// The algorithm is imperfect, but it works very well in almost all cases.
// TODO: Check other blocks in sector.
static void update_node_light(MTSector *, MTBlock *block, uint16_t idx)
{
	static const int16_t adjacent[] = {
		BLOCK_YSTRIDE, -BLOCK_YSTRIDE,
		BLOCK_XSTRIDE, -BLOCK_XSTRIDE,
		BLOCK_ZSTRIDE, -BLOCK_ZSTRIDE,
	};
	// Maximum light values of adjacent nodes with sun/without sun
	uint8_t max_l_s = 0, max_l_n = 0;
	for (unsigned i = 0; i < ARRAY_SIZE(adjacent); ++i) {
		const int16_t adj_idx = idx + adjacent[i];
		if (adj_idx < 0 || adj_idx >= NODES_PER_BLOCK) {
			// Assume that nodes out of range are LIGHT_SUN during the day
			max_l_s = LIGHT_MAX;
			continue;
		}
		const uint8_t l = block->param1[adj_idx];
		// Must be signed or below could underflow
		int8_t l_s = (l & 0x0F) - 1;
		int8_t l_n = ((l & 0xF0) >> 4) - 1;
		if (l_s > max_l_s) max_l_s = l_s;
		if (l_n > max_l_n) max_l_n = l_n;
		if (max_l_s + max_l_n >= 15*2) break;
	}
	block->param1[idx] = (max_l_n << 4) | max_l_s;
}


// As of MC 1.2, the top half of the door doesn't contain
// orientation data, it must be obtained from the bottom half.
static const MTNodeMetaStrings door_ms_right {{"right", "1"}};
static const MTNodeMeta door_meta_right(&door_ms_right, nullptr, false, false);

#if MC_VERSION < 102

static void old_door_set_right(MTSector *, MTBlock *block, uint16_t idx)
{
	block->meta.emplace_back(idx, &door_meta_right);
}

#else // else if MC_VERSION >= 102

static void finish_door(MTSector *sector, MTBlock *block, uint16_t idx)
{
	MTBlock *top_block = block;
	uint16_t top_idx = idx + BLOCK_YSTRIDE;
	if (top_idx >= NODES_PER_BLOCK) {
		top_block = sector->getBlock(block->pos.y + 1);
		assert(top_block != nullptr);
		// Top section is at (bottom_x, 0, bottom_z) in top block
		top_idx = idx & (BLOCK_IDX_MASK_X | BLOCK_IDX_MASK_Z);
	}

	uint8_t top_param2 = top_block->param2[top_idx];
	uint8_t bottom_param2 = block->param2[idx];

	bool open = bottom_param2 & 4;
	int8_t dir = bottom_param2 & 3; // Dir is in MT format
	bool hinge_right = !(top_param2 & 1);

	bool door_type = false;

	if (hinge_right) {
		door_type = !door_type;
		dir += 2;
		block->meta.emplace_back(idx, &door_meta_right);
		block->meta.emplace_back(top_idx, &door_meta_right);
	}

	if (open) {
		door_type = !door_type;
		dir += hinge_right ? -1 : 1;
	}

	if (dir > 3) dir -= 4;
	if (dir < 0) dir += 4;

	std::string door_name = MTMap::getName(block->content[idx]);
	door_name = door_name.substr(0, door_name.size() - 4);  // Remove _t_1/_b_2/etc
	content_t c_top, c_bottom;

	if (door_type) {
		c_top = MTMap::getId(door_name + "_t_2");
		c_bottom = MTMap::getId(door_name + "_b_2");
	} else {
		c_top = MTMap::getId(door_name + "_t_1");
		c_bottom = MTMap::getId(door_name + "_b_1");
	}

	block->content[idx] = c_bottom;
	block->param2[idx] = dir;
	top_block->content[top_idx] = c_top;
	top_block->param2[top_idx] = dir;
}

#endif  // MC_VERSION < 102


void convert_inventory(const NBT::List &be_items, std::vector<MTItemStack> &inv_items)
{
	for (uint32_t i = 0; i < be_items.size; ++i) {
		NBT::Compound & be_item = be_items.value[i];

		uint8_t slot = be_item["Slot"].as<NBT::Byte>();
		assert(slot < inv_items.size());
		MTItemStack & item = inv_items[slot];;

		// Used for wear *and* node data field
		NBT::Short data = be_item["Damage"];

		NBT::Tag id = be_item["id"];
		const ConversionData *cd;

		if (id.type == NBT::TagType::Short) {
			uint16_t id_i = id.as<NBT::Short>();
			if (!get_conversion(&cd, id_i, data)) {
				MTMap::reportUnknown(id_i, data);
				continue;
			}
		} else if (id.type == NBT::TagType::String) {
			NBT::String name(id);
			std::string name_s(name.value, name.size);
			if (!get_conversion(&cd, name_s, data)) {
				MTMap::reportUnknown(name_s, data);
				continue;
			}
		} else {
			std::cerr << "Warning: Unexpected item id type: "
				<< (int)id.type << ' ' << id.dump() << std::endl;
			continue;
		}

		item.item = cd->cid;
		item.count = be_item["Count"].as<NBT::Byte>();
		if (cd->tool)
			item.wear = data;
	}
}


std::pair<bool, MTNodeMeta*> convert_chest(const NBT::Tag &te,
		uint8_t, bool)
{
	static const MTNodeMetaStrings meta = {
		{"infotext", "Chest"},
		{"formspec", "size[8,9]"
			"list[current_name;main;0,0;8,4;]"
			"list[current_player;main;0,5;8,4;]"},
	};

	NBT::Compound &te_map = te;
	std::vector<MTItemStack> items(32, MTItemStack());
	auto it = te_map.find("Items");
	if (it != te_map.end())
		convert_inventory(it->second, items);

	auto * inv = new MTInventoryList {
		{"main", MTInventory(8, std::move(items))},
	};
	return std::make_pair(true, new MTNodeMeta(&meta, inv, false, true));
}


std::pair<bool, MTNodeMeta*> convert_furnace(const NBT::Tag &,
		uint8_t, bool)
{
	static MTNodeMetaStrings fields = {
		{"infotext", "Furnace out of fuel"},
		{"formspec", "size[8,9]"
			"image[2,2;1,1;default_furnace_fire_bg.png]"
			"list[current_name;fuel;2,3;1,1;]"
			"list[current_name;src;2,1;1,1;]"
			"list[current_name;dst;5,1;2,2;]"
			"list[current_player;main;0,5;8,4;]"},
		{"src_totaltime", "0"},
		{"src_time", "0"},
		{"fuel_totaltime", "0"},
		{"fuel_time", "0"}
	};
	// TODO: Convert inventory.
	static const std::vector<MTItemStack> inv_fuel(1, MTItemStack());
	static const std::vector<MTItemStack> inv_src(1, MTItemStack());
	static const std::vector<MTItemStack> inv_dst(4, MTItemStack());
	static MTInventoryList inv = {
		{"fuel", MTInventory(1, inv_fuel)},
		{"src", MTInventory(1, inv_src)},
		{"dst", MTInventory(2, inv_dst)},
	};
	static MTNodeMeta meta(&fields, &inv, false, false);
	return std::make_pair(false, &meta);
}


// Converts a UTF-8 string into the Lua table of Unicode codepoints that
// Mineclonia stores in the sign's "utext" metadata (core.serialize() of
// the codepoint list returned by mcl_signs.string_to_ustring).
static std::string utf8_codepoints_lua(const std::string &text)
{
	std::string out = "return {";
	size_t i = 0;
	bool first = true;
	while (i < text.size()) {
		unsigned char c = static_cast<unsigned char>(text[i]);
		uint32_t cp = c;
		size_t len = 1;
		if (c < 0x80) {
			cp = c;
		} else if ((c & 0xE0) == 0xC0) {
			cp = c & 0x1F; len = 2;
		} else if ((c & 0xF0) == 0xE0) {
			cp = c & 0x0F; len = 3;
		} else if ((c & 0xF8) == 0xF0) {
			cp = c & 0x07; len = 4;
		}
		for (size_t k = 1; k < len && i + k < text.size(); ++k)
			cp = (cp << 6) | (static_cast<unsigned char>(text[i + k]) & 0x3F);
		if (!first)
			out += ",";
		out += std::to_string(cp);
		first = false;
		i += len;
	}
	out += "}";
	return out;
}

// Extracts the plain text from a Minecraft 1.20+ sign message, which is a
// JSON text component like {"text":"w"} or a bare quoted string.
static std::string json_text_component(const std::string &msg)
{
	// "text" field of {"text":"..."}
	size_t key = msg.find("\"text\"");
	if (key != std::string::npos) {
		size_t colon = msg.find(':', key);
		size_t q1 = colon == std::string::npos ? std::string::npos :
				msg.find('"', colon + 1);
		if (q1 != std::string::npos) {
			std::string out;
			bool esc = false;
			for (size_t i = q1 + 1; i < msg.size(); ++i) {
				char c = msg[i];
				if (esc) {
					switch (c) {
					case 'n': out += '\n'; break;
					case 't': out += '\t'; break;
					case 'r': out += '\r'; break;
					case '\\': out += '\\'; break;
					case '"': out += '"'; break;
					default: out += c; break;
					}
					esc = false;
				} else if (c == '\\') {
					esc = true;
				} else if (c == '"') {
					break;
				} else {
					out += c;
				}
			}
			return out;
		}
	}
	// Bare JSON string: "w"
	if (msg.size() >= 2 && msg.front() == '"' && msg.back() == '"')
		return msg.substr(1, msg.size() - 2);
	return msg;
}

// Minecraft sign dye name -> Mineclonia mcl_dyes hex RGB.
static const char *sign_color_rgb(const std::string &mc_color)
{
	if (mc_color == "white") return "#d0d6d7";
	if (mc_color == "orange") return "#e26501";
	if (mc_color == "magenta") return "#ab31a2";
	if (mc_color == "light_blue") return "#258ec9";
	if (mc_color == "yellow") return "#f1b216";
	if (mc_color == "lime") return "#60ac19";
	if (mc_color == "pink") return "#d56791";
	if (mc_color == "gray") return "#383c40";      // mcl grey
	if (mc_color == "light_gray") return "#818177"; // mcl silver
	if (mc_color == "cyan") return "#167b8c";
	if (mc_color == "purple") return "#6821a0";
	if (mc_color == "blue") return "#2e3094";
	if (mc_color == "brown") return "#633d20";
	if (mc_color == "green") return "#4b5e25";
	if (mc_color == "red") return "#912222";
	if (mc_color == "black") return "#080a10";
	return nullptr;
}

// Reads the four message lines from a modern 1.20+ sign side compound
// (front_text / back_text) and appends them to "text" joined by \n.
// Returns false if the side has no messages list.
static bool modern_sign_side_text(const NBT::Tag &side, std::string *text)
{
	const NBT::Compound & side_map = side;
	auto mit = side_map.find("messages");
	if (mit == side_map.end())
		return false;
	const NBT::List & msgs = mit->second;
	for (unsigned i = 0; i < msgs.size; ++i) {
		const NBT::String & line = msgs.value[i].as<NBT::String>();
		std::string sline(line.value, line.size);
		if (i > 0)
			*text += '\n';
		*text += json_text_component(sline);
	}
	return true;
}

std::pair<bool, MTNodeMeta*> convert_sign(const NBT::Tag &te,
		uint8_t, bool)
{
	// Modern 1.20+ sign: text lives in front_text/back_text compounds
	// with JSON messages, a dye color and a glow flag.  Mineclonia signs
	// are single-sided, so the front text wins and the back text is used
	// only when the front is empty.
	const NBT::Compound & te_map = te;
	auto ft_it = te_map.find("front_text");
	if (ft_it != te_map.end()) {
		std::string text;
		modern_sign_side_text(ft_it->second, &text);
		if (text.empty()) {
			auto bt_it = te_map.find("back_text");
			if (bt_it != te_map.end())
				modern_sign_side_text(bt_it->second, &text);
		}

		MTNodeMetaStrings * fields = new MTNodeMetaStrings;
		if (!text.empty()) {
			(*fields)["utext"] = utf8_codepoints_lua(text);
			(*fields)["infotext"] = '"' + text + '"';
		}

		// Color: dye name -> hex RGB (skip when black, the default).
		const NBT::Compound & ft_map = ft_it->second;
		std::string color;
		auto cit = ft_map.find("color");
		if (cit != ft_map.end())
			color = cit->second.as<NBT::String>().value;
		const char * rgb = sign_color_rgb(color);
		if (rgb && std::string(rgb) != "#080a10")
			(*fields)["color"] = rgb;

		// Glow flag.
		auto git = ft_map.find("has_glowing_text");
		if (git != ft_map.end() && git->second.as<NBT::Byte>() != 0)
			(*fields)["glow"] = "true";

		return std::make_pair(true, new MTNodeMeta(fields, nullptr, true, false));
	}

	// Legacy pre-1.20 sign: Text1..Text4 fields.
	std::string text;
	for (unsigned i = 1; i < 5; ++i) {
		NBT::String line = te["Text" + std::to_string(i)];
		if (!line.size)
			continue;
		std::string sline(line.value, line.size);
		rtrim(sline);
		if (!sline.empty())
			text += sline + " ";
	}
	rtrim(text);
	auto * fields = new MTNodeMetaStrings {
		{"infotext", '"'+text+'"'},
		{"text", text},
		{"formspec", "field[text;;${text}]"},
	};
	return std::make_pair(true, new MTNodeMeta(fields, nullptr, true, false));
}


// MC banner base-color index (white=0..black=15) -> Mineclonia banner
// item dye key (mcl_banners:banner_item_<key>).
static const char *banner_dye_key(uint8_t base_color)
{
	static const char *keys[16] = {
		"white", "orange", "magenta", "light_blue", "yellow", "lime",
		"pink", "grey", "silver", "cyan", "purple", "blue", "brown",
		"green", "red", "black",
	};
	return keys[base_color & 0xF];
}

// MC pattern color name -> Mineclonia "unicolor_*" layer color.
static std::string banner_unicolor(const std::string &mc_color)
{
	static const std::map<std::string, std::string> m = {
		{"white", "unicolor_white"},
		{"orange", "unicolor_orange"},
		{"magenta", "unicolor_red_violet"},
		{"light_blue", "unicolor_light_blue"},
		{"yellow", "unicolor_yellow"},
		{"lime", "unicolor_green"},
		{"pink", "unicolor_light_red"},
		{"gray", "unicolor_darkgrey"},
		{"light_gray", "unicolor_grey"},
		{"cyan", "unicolor_cyan"},
		{"purple", "unicolor_violet"},
		{"blue", "unicolor_blue"},
		{"brown", "unicolor_dark_orange"},
		{"green", "unicolor_dark_green"},
		{"red", "unicolor_red"},
		{"black", "unicolor_black"},
	};
	auto it = m.find(mc_color);
	return it == m.end() ? "unicolor_white" : it->second;
}

// MC banner pattern name (e.g. "minecraft:rhombus") -> Mineclonia pattern
// key.  The Mojang logo is called "thing" in Mineclonia.
static std::string banner_pattern_key(const std::string &pattern)
{
	std::string p = pattern;
	size_t colon = p.find(':');
	if (colon != std::string::npos)
		p = p.substr(colon + 1);
	if (p == "mojang")
		return "thing";
	return p;
}

// Escapes a string the same way Luanti's serializeJsonString does (used
// for item metadata inside mapblock inventory serialization).
static std::string json_escape(const std::string &s)
{
	static const char hex[] = "0123456789abcdef";
	std::string out;
	out.reserve(s.size() + 2);
	out.push_back('"');
	for (unsigned char c : s) {
		switch (c) {
		case '"': out += "\\\""; break;
		case '\\': out += "\\\\"; break;
		case '\b': out += "\\b"; break;
		case '\f': out += "\\f"; break;
		case '\n': out += "\\n"; break;
		case '\r': out += "\\r"; break;
		case '\t': out += "\\t"; break;
		default:
			if (c < 32 || c == 127) {
				out += "\\u00";
				out.push_back(hex[c >> 4]);
				out.push_back(hex[c & 0xF]);
			} else {
				out.push_back(static_cast<char>(c));
			}
		}
	}
	out.push_back('"');
	return out;
}

// Returns the item name JSON-quoted only when it contains characters that
// require it (same rule as serializeJsonStringIfNeeded).
static std::string json_string_if_needed(const std::string &s)
{
	for (unsigned char c : s) {
		if (c <= 0x1f || c >= 0x7f || c == ' ' || c == '"')
			return json_escape(s);
	}
	return s;
}

// Converts a Minecraft banner block entity (1.13+ and 1.21+, where the
// base color is in the block name and patterns are string colors) into the
// Mineclonia banner node metadata: a colored banner item (with the
// patterns in the item's "layers" metadata) inside the node's "banner"
// inventory, plus the rotation level for the entity.
std::pair<bool, MTNodeMeta*> convert_banner(const NBT::Tag &te,
		uint8_t data, bool hanging)
{
	uint8_t base_color = data >> 4;
	uint8_t state = data & 0xF;

	// Mirror the rotation for the converted (180-degree-rotated) world.
	int rotation_level;
	if (hanging) {
		// wallmounted param2 (north=4, south=5, east=3, west=2) -> level:
		// north->8, south->0, east->4, west->12.
		switch (state) {
		case 2: rotation_level = 12; break;
		case 3: rotation_level = 4;  break;
		case 4: rotation_level = 8;  break;
		default: rotation_level = 0; break;
		}
	} else {
		// Standing banner: MC rotation r -> (16 - r) % 16.
		rotation_level = (16 - state) % 16;
	}

	// Mineclonia keeps the patterns on the banner item stack, in a
	// "layers" metadata key holding core.serialize() output.
	std::string layers_lua;
	const NBT::Compound & te_map = te;
	auto pit = te_map.find("patterns");
	if (pit != te_map.end()) {
		const NBT::List & pats = pit->second;
		if (pats.size > 0) {
			layers_lua = "return {\n";
			for (unsigned i = 0; i < pats.size; ++i) {
				const NBT::Compound & p = pats.value[i];
				std::string color = "unicolor_white";
				auto cit = p.find("color");
				if (cit != p.end())
					color = banner_unicolor(cit->second.as<std::string>());
				std::string pat = "base";
				auto pat_it = p.find("pattern");
				if (pat_it != p.end())
					pat = banner_pattern_key(
							pat_it->second.as<std::string>());
				layers_lua += "\t{\n";
				layers_lua += "\t\tcolor = \"" + color + "\",\n";
				layers_lua += "\t\tpattern = \"" + pat + "\",\n";
				layers_lua += "\t},\n";
			}
			layers_lua += "}\n";
		}
	}

	MTItemStack stack;
	stack.item = MTMap::getId("mcl_banners:banner_item_" +
			std::string(banner_dye_key(base_color)));
	stack.count = 1;
	if (!layers_lua.empty()) {
		// ItemStackMetadata serialization: \x01 <key> \x02 <value> \x03
		std::string meta_blob = std::string("\x01", 1) + "layers" +
				std::string("\x02", 1) + layers_lua +
				std::string("\x03", 1);
		stack.meta = json_escape(meta_blob);
	}

	std::vector<MTItemStack> items;
	items.push_back(stack);
	auto * inv = new MTInventoryList {
		{"banner", MTInventory(1, std::move(items))},
	};
	auto * fields = new MTNodeMetaStrings {
		{"rotation_level", std::to_string(rotation_level)},
	};
	return std::make_pair(true, new MTNodeMeta(fields, inv, true, true));
}


std::map<std::string, BlockEntityCB> be_convert {
	{"Chest", convert_chest},
	{"Furnace", convert_furnace},
	{"Sign", convert_sign},
	{"sign", convert_sign},
	{"wall_sign", convert_sign},
	{"hanging_sign", convert_sign},
	{"wall_hanging_sign", convert_sign},
	{"banner", convert_banner},
};

static void init_conversion_table()
{
	#include "conversions.h"
}

void init_conversions()
{
	static bool conversions_initialized = false;
	if (conversions_initialized)
		return;
	conversions_initialized = true;

	init_conversion_table();
}

void load_custom_conversions(const std::string &input_world,
		const std::string &output_world)
{
	std::ifstream map_file(input_world + "/mc2mt-blockmap.tsv");
	if (!map_file)
		return;

	std::ofstream worldmod(output_world + "/worldmods/__mc2mt/init.lua",
			std::ios::app);
	if (!worldmod)
		throw std::runtime_error("Could not open generated MC2MT worldmod");

	std::string line;
	while (std::getline(map_file, line)) {
		if (line.empty() || line[0] == '#')
			continue;
		std::istringstream row(line);
		uint16_t id;
		unsigned data;
		std::string node, state;
		if (!(row >> id >> data >> node >> state) || data > MC_DATA_MAX)
			throw std::runtime_error("Invalid mc2mt-blockmap.tsv row: " + line);

		content_t cid = MTMap::getId(node);
		custom_conversion_map[custom_key(id, static_cast<uint8_t>(data))] =
			ConversionData{false, 0, cid, nullptr};

		// Only register nodes that are not already provided by Mineclonia.
		// Real node names (e.g. mcl_core:stone) already exist; registering
		// them again would abort world loading.
		if (node.compare(0, 8, "__mc2mt:") == 0) {
			worldmod << "core.register_node(\"" << node << "\", {\n"
				<< "  description = \"Imported Minecraft block "
				<< id << ":" << data << "\",\n"
				<< "  tiles = {\"default_stone.png\"},\n"
				<< "  is_ground_content = false,\n"
				<< "  groups = {handy = 1, pickaxey = 1, building_block = 1}\n"
				<< "})\n";
		}
	}
}
