#include "nbt/nbt.hpp"
#include "util.hpp"
#include "Map.hpp"

#include <vector>
#include <string>
#include <map>
#include <fstream>


class MTBlock;
class MCBlock;


enum class MCFormat { Regions, Anvil };

struct MCPos { int32_t x; uint8_t y; int32_t z; };
struct MCChunkPos { int32_t x, z; };


// Groups contain a 32x32 set of chunks
struct MCGroup {
	MCGroup(const std::string &name, int32_t x, int32_t z, MCFormat format) :
		name(name), x(x), z(z), format(format), f(nullptr) {}
	~MCGroup() { delete f; }

	std::string name;
	int32_t x, z;
	MCFormat format;
	std::ifstream * f;
};


// Chunks are a vertical stack of blocks
// TODO: Use simple array?
typedef std::vector<MCBlock *> MCChunk;

typedef std::vector<MCChunkPos> MCChunkList;


class MCMap {
public:
	MCMap(const std::string & path);
	// You must free added groups
	void listGroups(std::vector<MCGroup*> &);
	void listChunks(MCGroup * gid, MCChunkList * group);
	// You must free the chunk's blocks
	bool loadChunk(MCChunk * chunk, const MCGroup & gid, MCChunkPos cp);

	// Single-threaded pre-pass over a modern (1.18+) world: collects every
	// distinct block state into modern_registry and computes modern_shift_sub
	// so content below Y=0 fits inside the 256-block height MC2MT supports.
	void scanModern();

private:
	// You must free the chunk's blocks
	bool readChunk(MCChunk * chunk, std::ifstream * f, MCChunkPos cp,
			MCFormat format);
	// Reads + decompresses one chunk payload into `data`; false if absent.
	bool readChunkData(std::ifstream * f, MCChunkPos cp, std::string &data);

	const std::string path;
	NBT::Tag meta;
};


/// A 16x16x16 block
class MCBlock {
	friend class MTBlock;
public:
	MCBlock(const NBT::Tag & chunk, MCChunkPos cp,
		 uint8_t y_slice, MCFormat format,
		 const NBT::Tag &sec = NBT::TagType::End, bool modern = false);
	MCBlock(const MCBlock &) = delete;

	MCPos pos;

	// True when blocks[] already holds final Luanti content ids (modern
	// world), so MTBlock can skip the numeric conversion table.
	bool direct_content;

private:
	void fromSection(const NBT::Tag & section);
	void fromModernSection(const NBT::Tag & section);
	void fromChunk(const NBT::Tag & chunk, uint8_t y_slice);

	static void reverseXAxis(uint16_t * data, const uint8_t * l);
	static void expandHalfBytes(uint8_t * data, const uint8_t * l);
	static void extractSlice(uint16_t * data, const uint8_t * l,
			uint8_t y_slice);
	static void extractSliceHalfBytes(uint8_t * data, const uint8_t * l,
			uint8_t y_slice);

	std::vector<NBT::Tag> tile_entities;
	uint16_t blocks[NODES_PER_BLOCK];
	uint8_t data[NODES_PER_BLOCK];
	uint8_t sky_light[NODES_PER_BLOCK];
	uint8_t block_light[NODES_PER_BLOCK];
};
