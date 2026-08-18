#pragma once

#include "Map.hpp"

#include <string>
#include <map>
#include <set>
#include <vector>

// Maps a raw Minecraft block base name (e.g. "stone", "oak_planks",
// "stripped_oak_log") to a Mineclonia node name, or a "__mc2mt:blk_*"
// fallback node name for states without a Mineclonia equivalent.
std::string modern_node_for(const std::string &base_name);

// Global registry that assigns each distinct block state a content id.
//
// The scan phase (single threaded) calls add() for every base name it sees,
// then finalize() resolves each name to a content id.  The conversion phase
// (multi threaded) then only reads the immutable name -> id map via lookup().
class ModernStateRegistry {
public:
	void add(const std::string &base_name);
	void finalize();
	content_t lookup(const std::string &base_name) const;

	// Append core.register_node() calls for every fallback node to the
	// generated worldmod so Mineclonia can load the world.
	void write_worldmod(const std::string &output_world) const;

private:
	std::set<std::string> names;
	std::map<std::string, content_t> name_to_id;
	std::vector<std::string> fallback_nodes;
};

extern ModernStateRegistry modern_registry;
extern int modern_shift_sub;
extern bool modern_enabled;
