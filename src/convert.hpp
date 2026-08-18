#pragma once

#include "Map.hpp"
#include "nbt/nbt.hpp"

#define MC_VERSION 109

struct MTNodeMeta;
class MTSector;
class MTBlock;

typedef void (*ConversionCallback)(MTSector *sector, MTBlock *block, uint16_t idx);

struct ConversionData {
	bool tool;
	uint8_t param2;
	content_t cid;
	ConversionCallback cb;
};


bool get_conversion(const ConversionData **cd, uint16_t id, uint16_t data);
bool get_conversion(const ConversionData **cd, const std::string &name, uint16_t data);

// Converts a Minecraft block entity to Luanti node metadata.  The extra
// arguments carry per-node state from the direct (modern) path: `data`
// holds (base_color << 4) | state for banners and the palette index for
// candles, and `hanging` marks wall banners.  Legacy converters ignore
// them.
typedef std::pair<bool, MTNodeMeta *> (*BlockEntityCB)(const NBT::Tag &,
		uint8_t data, bool hanging);
extern std::map<std::string, BlockEntityCB> be_convert;


void init_conversions();

// Load synthetic block IDs emitted by the Amulet bridge. The file also
// causes visible fallback nodes to be registered in the generated worldmod.
void load_custom_conversions(const std::string &input_world,
		const std::string &output_world);
