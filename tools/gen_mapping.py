#!/usr/bin/env python3
"""Generate the extended block mapping for MC2MT's modern.cpp.

Ground truth:
  - Minecraft 1.21+ block ids: vanilla blockstates file names
  - Mineclonia node names: string literals found in the installed game
    (grep of all *.lua) + known dynamic names registered by API helpers
  - Texture-name pairs from the user's craft_to_clonia_textures converter
    (parsed, never modified)
"""
import json, os, re, sys

# ---------------------------------------------------------------------------
# 1. Load ground truth
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
MC_BLOCKS = [l.strip() for l in open(os.path.join(HERE, "mc_blocks.txt")) if l.strip()]
MCL_NODES = set(l.strip() for l in open(os.path.join(HERE, "mcl_all_nodes.txt")) if l.strip())

# Dynamic node names that exist at runtime but appear as string concatenation
# in the game source. Verified against the game's API helpers.
WOODS_MCL = ["oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
             "mangrove", "cherry_blossom", "bamboo", "crimson", "warped",
             "pale_oak"]
COLORS_MCL = ["white", "silver", "grey", "black", "red", "orange", "yellow",
              "lime", "green", "cyan", "light_blue", "blue", "purple",
              "magenta", "pink", "brown"]
STAIR_SUBNAMES = ["stone", "stone_rough", "andesite", "andesite_smooth",
                  "granite", "granite_smooth", "diorite", "diorite_smooth",
                  "cobble", "mossycobble", "brick_block", "sandstone",
                  "sandstonesmooth", "sandstonesmooth2", "redsandstone",
                  "redsandstonesmooth", "redsandstonesmooth2", "stonebrick",
                  "stonebrickcracked", "stonebrickmossy", "quartzblock",
                  "quartz_smooth", "nether_brick", "red_nether_brick",
                  "end_bricks", "end_stone", "purpur_block", "prismarine",
                  "prismarine_brick", "prismarine_dark", "goldblock",
                  "ironblock", "lapisblock", "blackstone",
                  "blackstone_polished", "blackstone_brick_polished",
                  "deepslate", "deepslate_cobbled", "deepslate_polished",
                  "deepslate_bricks", "deepslate_tiles", "deepslate_chiseled",
                  "tuff", "tuff_polished", "tuff_bricks",
                  "copper_cut", "copper_exposed_cut", "copper_oxidized_cut",
                  "copper_weathered_cut", "resin_brick",
                  "hardened_clay"] + [f"hardened_clay_{c}" for c in COLORS_MCL] \
                 + [f"concrete_{c}" for c in COLORS_MCL]

def dynamic_nodes():
    d = set()
    for w in WOODS_MCL:
        d.add(f"mcl_trees:wood_{w}")
        d.add(f"mcl_trees:tree_{w}")
        d.add(f"mcl_trees:stripped_{w}")
        d.add(f"mcl_trees:bark_{w}")
        d.add(f"mcl_trees:bark_stripped_{w}")
        d.add(f"mcl_trees:sapling_{w}")
        d.add(f"mcl_trees:leaves_{w}")
        d.add(f"mcl_fences:{w}_fence")
        d.add(f"mcl_fences:{w}_fence_gate")
        for half in ("b", "t"):
            for state in ("1", "2"):
                d.add(f"mcl_doors:door_{w}_{half}_{state}")
        d.add(f"mcl_doors:trapdoor_{w}")
        d.add(f"mcl_doors:trapdoor_{w}_open")
        d.add(f"mcl_stairs:stair_{w}")
        d.add(f"mcl_stairs:slab_{w}")
        d.add(f"mcl_buttons:button_{w}_off")
        d.add(f"mcl_pressureplates:pressure_plate_{w}_off")
        d.add(f"mcl_signs:standing_sign_{w}")
        d.add(f"mcl_signs:wall_sign_{w}")
        d.add(f"mcl_signs:hanging_sign_{w}")
        d.add(f"mcl_signs:hanging_sign_wall_{w}")
        d.add(f"mcl_signs:hanging_sign_attached_{w}")
    for s in STAIR_SUBNAMES:
        d.add(f"mcl_stairs:stair_{s}")
        d.add(f"mcl_stairs:slab_{s}")
        d.add(f"mcl_stairs:stair_{s}_inner")
        d.add(f"mcl_stairs:stair_{s}_outer")
        d.add(f"mcl_stairs:slab_{s}_double")
        d.add(f"mcl_stairs:slab_{s}_top")
    # Iron and copper door APIs generate their state nodes dynamically.
    for prefix in ("mcl_doors:iron_door", "mcl_copper:door",
                   "mcl_copper:door_exposed", "mcl_copper:door_weathered",
                   "mcl_copper:door_oxidized"):
        for half in ("b", "t"):
            for state in ("1", "2"):
                d.add(f"{prefix}_{half}_{state}")
    for prefix in ("mcl_doors:iron_trapdoor", "mcl_copper:trapdoor",
                   "mcl_copper:trapdoor_exposed", "mcl_copper:trapdoor_weathered",
                   "mcl_copper:trapdoor_oxidized"):
        d.add(prefix)
        d.add(prefix + "_open")
    for c in COLORS_MCL:
        d.add(f"mcl_wool:{c}")
        d.add(f"mcl_wool:{c}_carpet")
        d.add(f"mcl_colorblocks:hardened_clay_{c}")
        d.add(f"mcl_colorblocks:glazed_terracotta_{c}")
        d.add(f"mcl_colorblocks:concrete_{c}")
        d.add(f"mcl_colorblocks:concrete_powder_{c}")
        d.add(f"mcl_core:glass_{c}")
        d.add(f"mcl_panes:pane_{c}")
        d.add(f"mcl_candles:candle_{c}")
    # walls (mcl_walls / mcl_deepslate / mcl_blackstone)
    for w in ["cobble", "mossycobble", "stonebrick", "stonebrickmossy",
              "andesite", "granite", "diorite", "brick",
              "sandstone", "redsandstone", "prismarine",
              "netherbrick", "rednetherbrick",
              "endbricks", "mudbrick"]:
        d.add(f"mcl_walls:{w}")
    for w in ["deepslatecobbled", "deepslatepolished",
              "deepslatebricks", "deepslatetiles",
              "tuffpolished", "tuffbricks"]:
        d.add(f"mcl_deepslate:{w}wall")
    for w in ["wall", "polishedwall", "polishedbrickwall"]:
        d.add(f"mcl_blackstone:{w}")
    d.add("mcl_vaults:vault")
    d.add("mcl_vaults:ominous_vault")
    # Light blocks are registered dynamically (for i = 0, 14) in
    # nodes_misc.lua, so they never appear in colors.json.
    for n in range(15):
        d.add(f"mcl_core:light_{n}")
    # Suspicious blocks (mcl_sus_nodes), plain + brushing variants.
    for s in ["gravel", "sand"]:
        d.add(f"mcl_sus_nodes:{s}")
        d.add(f"mcl_sus_nodes:{s}_1")
        d.add(f"mcl_sus_nodes:{s}_2")
        d.add(f"mcl_sus_nodes:{s}_3")
    # Dripstone stages are registered dynamically in a loop
    # (dripstone_top_* stalactites, dripstone_bottom_* stalagmites).
    for d2 in ("top", "bottom"):
        for stage in ("tip_merge", "tip", "frustum", "middle", "base"):
            d.add(f"mcl_dripstone:dripstone_{d2}_{stage}")
    d.add("mcl_flowers:wildflowers")
    d.add("mcl_flowers:wildflowers_1")
    d.add("mcl_flowers:wildflowers_2")
    d.add("mcl_flowers:wildflowers_3")
    d.add("mcl_flowers:wildflowers_4")
    d.add("mcl_copper:block_chiseled")
    d.add("mcl_copper:block_exposed_chiseled")
    d.add("mcl_copper:block_weathered_chiseled")
    d.add("mcl_copper:block_oxidized_chiseled")
    d.add("mcl_copper:bulb_exposed")
    d.add("mcl_copper:bulb_weathered")
    d.add("mcl_copper:bulb_oxidized")
    d.add("mcl_comparators:comparator_off_comp")
    d.add("mcl_comparators:comparator_off_sub")
    d.add("mcl_comparators:comparator_on_comp")
    d.add("mcl_comparators:comparator_on_sub")
    d.add("mcl_repeaters:repeater_off_1")
    d.add("mcl_heads:creeper")
    d.add("mcl_heads:dragon")
    d.add("mcl_heads:skeleton")
    d.add("mcl_heads:wither_skeleton")
    d.add("mcl_heads:zombie")
    d.add("mcl_heads:steve")
    d.add("mcl_beds:bed_white_bottom")
    for c in COLORS_MCL:
        d.add(f"mcl_beds:bed_{c}_bottom")
    d.add("mcl_crimson:crimson_fungus")
    d.add("mcl_crimson:warped_fungus")
    d.add("mcl_cocoas:cocoa_0")
    d.add("mcl_cocoas:cocoa_1")
    d.add("mcl_cocoas:cocoa_2")
    d.add("mcl_core:emeraldblock")
    d.add("mcl_core:deadbush")
    d.add("mcl_core:cactus_flower")
    d.add("mcl_flowers:cornflower")
    d.add("mcl_flowers:lily_of_the_valley")
    d.add("mcl_redstone:redstone")
    d.add("mcl_redstone_torch:redstoneblock")
    d.add("mcl_candles:candle")
    d.add("mcl_candles:candle_cake")
    d.add("mcl_cake:cake")
    d.add("mcl_walls:mudbrick")
    d.add("mcl_ocean:brain_coral")
    d.add("mcl_ocean:brain_coral_block")
    d.add("mcl_ocean:brain_coral_fan")
    d.add("mcl_ocean:bubble_coral")
    d.add("mcl_ocean:bubble_coral_block")
    d.add("mcl_ocean:bubble_coral_fan")
    d.add("mcl_ocean:fire_coral")
    d.add("mcl_ocean:fire_coral_block")
    d.add("mcl_ocean:fire_coral_fan")
    d.add("mcl_ocean:horn_coral")
    d.add("mcl_ocean:horn_coral_block")
    d.add("mcl_ocean:horn_coral_fan")
    d.add("mcl_ocean:tube_coral")
    d.add("mcl_ocean:tube_coral_block")
    d.add("mcl_ocean:tube_coral_fan")
    for t in ["brain", "bubble", "fire", "horn", "tube"]:
        d.add(f"mcl_ocean:dead_{t}_coral")
        d.add(f"mcl_ocean:dead_{t}_coral_block")
        d.add(f"mcl_ocean:dead_{t}_coral_fan")
    return d

DYNAMIC = dynamic_nodes()

def node_ok(name):
    if name in MCL_NODES or name in DYNAMIC or name == "air":
        return True
    # Registered in the game but absent from colors.json (invisible nodes)
    if name in ("mcl_core:barrier", "mcl_core:realm_barrier"):
        return True
    return False

# ---------------------------------------------------------------------------
# 2. Curated direct mapping (MC block id -> Mineclonia node)
# ---------------------------------------------------------------------------
D = {}

def add(mc, cl, note=""):
    D[mc] = cl

# Stairs: the converter threads the MC `shape` block state (|straight /
# |outer_left / |outer_right / |inner_left / |inner_right) which picks the
# Mineclonia node (stair_x / stair_x_outer / stair_x_inner).  Emit all five
# keys for every stair block.
def add_stair_shapes(mc, base_node):
    for sh, node in (("straight", ""), ("outer_left", "_outer"),
                     ("outer_right", "_outer"), ("inner_left", "_inner"),
                     ("inner_right", "_inner")):
        FULL[f"{mc}|{sh}"] = base_node + node

# ---- core / stone ----
add("stone", "mcl_core:stone")
add("granite", "mcl_core:granite")
add("polished_granite", "mcl_core:granite_smooth")
add("diorite", "mcl_core:diorite")
add("polished_diorite", "mcl_core:diorite_smooth")
add("andesite", "mcl_core:andesite")
add("polished_andesite", "mcl_core:andesite_smooth")
add("cobblestone", "mcl_core:cobble")
add("mossy_cobblestone", "mcl_core:mossycobble")
add("stone_bricks", "mcl_core:stonebrick")
add("chiseled_stone_bricks", "mcl_core:stonebrickcarved")
add("cracked_stone_bricks", "mcl_core:stonebrickcracked")
add("mossy_stone_bricks", "mcl_core:stonebrickmossy")
add("smooth_stone", "mcl_core:stone_smooth")
add("sandstone", "mcl_core:sandstone")
add("chiseled_sandstone", "mcl_core:sandstonecarved")
add("cut_sandstone", "mcl_core:sandstonesmooth")
add("smooth_sandstone", "mcl_core:sandstonesmooth2")
add("red_sand", "mcl_core:redsand")
add("red_sandstone", "mcl_core:redsandstone")
add("chiseled_red_sandstone", "mcl_core:redsandstonecarved")
add("cut_red_sandstone", "mcl_core:redsandstonesmooth")
add("smooth_red_sandstone", "mcl_core:redsandstonesmooth2")
add("grass_block", "mcl_core:dirt_with_grass")
add("dirt", "mcl_core:dirt")
add("coarse_dirt", "mcl_core:coarse_dirt")
add("podzol", "mcl_core:podzol")
add("mycelium", "mcl_core:mycelium")
add("rooted_dirt", "mcl_lush_caves:rooted_dirt")
add("grass_path", "mcl_core:grass_path")
add("dirt_path", "mcl_core:grass_path")
add("sand", "mcl_core:sand")
add("gravel", "mcl_core:gravel")
add("clay", "mcl_core:clay")
add("obsidian", "mcl_core:obsidian")
add("crying_obsidian", "mcl_core:crying_obsidian")
add("bedrock", "mcl_core:bedrock")
add("barrier", "mcl_core:barrier")
add("brick_block", "mcl_core:brick_block")
add("glass", "mcl_core:glass")
add("ice", "mcl_core:ice")
add("packed_ice", "mcl_core:packed_ice")
add("blue_ice", "mcl_core:blue_ice")
add("frosted_ice", "mcl_core:ice")
add("snow_block", "mcl_core:snowblock")
add("snow", "mcl_core:snow")
add("bookshelf", "mcl_books:bookshelf")
add("chiseled_bookshelf", "mcl_books:bookshelf")
add("glowstone", "mcl_nether:glowstone")
add("netherrack", "mcl_nether:netherrack")
add("soul_sand", "mcl_nether:soul_sand")
add("soul_soil", "mcl_blackstone:soul_soil")
add("nether_bricks", "mcl_nether:nether_brick")
add("chiseled_nether_bricks", "mcl_nether:chiseled_nether_brick")
add("cracked_nether_bricks", "mcl_nether:cracked_nether_brick")
add("red_nether_bricks", "mcl_nether:red_nether_brick")
add("gold_block", "mcl_core:goldblock")
add("iron_block", "mcl_core:ironblock")
add("diamond_block", "mcl_core:diamondblock")
add("emerald_block", "mcl_core:emeraldblock")
add("bricks", "mcl_core:brick_block")
add("lapis_block", "mcl_core:lapisblock")
add("redstone_block", "mcl_redstone_torch:redstoneblock")
add("coal_block", "mcl_core:coalblock")
add("netherite_block", "mcl_nether:netheriteblock")
add("coal_ore", "mcl_core:stone_with_coal")
add("iron_ore", "mcl_core:stone_with_iron")
add("gold_ore", "mcl_core:stone_with_gold")
add("diamond_ore", "mcl_core:stone_with_diamond")
add("emerald_ore", "mcl_core:stone_with_emerald")
add("lapis_ore", "mcl_core:stone_with_lapis")
add("redstone_ore", "mcl_core:stone_with_redstone")
add("copper_ore", "mcl_copper:stone_with_copper")
add("nether_quartz_ore", "mcl_nether:quartz_ore")
add("nether_gold_ore", "mcl_blackstone:nether_gold")
add("ancient_debris", "mcl_nether:ancient_debris")
add("magma_block", "mcl_nether:magma")
add("sea_lantern", "mcl_ocean:sea_lantern")
add("prismarine", "mcl_ocean:prismarine")
add("prismarine_bricks", "mcl_ocean:prismarine_brick")
add("dark_prismarine", "mcl_ocean:prismarine_dark")
add("quartz_block", "mcl_nether:quartz_block")
add("quartz_bricks", "mcl_blackstone:quartz_brick")
add("smooth_quartz", "mcl_nether:quartz_smooth")
add("chiseled_quartz_block", "mcl_nether:quartz_chiseled")
add("quartz_pillar", "mcl_nether:quartz_pillar")
add("hay_block", "mcl_farming:hay_block")
add("dried_kelp_block", "mcl_ocean:dried_kelp_block")
add("cobweb", "mcl_core:cobweb")
add("slime_block", "mcl_core:slimeblock")
add("honey_block", "mcl_honey:honey_block")
add("honeycomb_block", "mcl_honey:honeycomb_block")
add("bone_block", "mcl_core:bone_block")
add("sponge", "mcl_sponges:sponge")
add("wet_sponge", "mcl_sponges:sponge_wet")
add("dead_bush", "mcl_core:deadbush")
add("tnt", "mcl_tnt:tnt")

# ---- deepslate family ----
add("deepslate", "mcl_deepslate:deepslate")
add("cobbled_deepslate", "mcl_deepslate:deepslate_cobbled")
add("polished_deepslate", "mcl_deepslate:deepslate_polished")
add("deepslate_bricks", "mcl_deepslate:deepslate_bricks")
add("cracked_deepslate_bricks", "mcl_deepslate:deepslate_bricks_cracked")
add("deepslate_tiles", "mcl_deepslate:deepslate_tiles")
add("cracked_deepslate_tiles", "mcl_deepslate:deepslate_tiles_cracked")
add("chiseled_deepslate", "mcl_deepslate:deepslate_chiseled")
add("reinforced_deepslate", "mcl_deepslate:deepslate_reinforced")
add("infested_deepslate", "mcl_monster_eggs:monster_egg_deepslate")
add("deepslate_coal_ore", "mcl_deepslate:deepslate_with_coal")
add("deepslate_iron_ore", "mcl_deepslate:deepslate_with_iron")
add("deepslate_gold_ore", "mcl_deepslate:deepslate_with_gold")
add("deepslate_diamond_ore", "mcl_deepslate:deepslate_with_diamond")
add("deepslate_emerald_ore", "mcl_deepslate:deepslate_with_emerald")
add("deepslate_lapis_ore", "mcl_deepslate:deepslate_with_lapis")
add("deepslate_redstone_ore", "mcl_deepslate:deepslate_with_redstone")
add("deepslate_copper_ore", "mcl_deepslate:deepslate_with_copper")
add("tuff", "mcl_deepslate:tuff")
add("tuff_bricks", "mcl_deepslate:tuff_bricks")
add("chiseled_tuff", "mcl_deepslate:tuff_chiseled")
add("chiseled_tuff_bricks", "mcl_deepslate:tuff_chiseled_bricks")
add("polished_tuff", "mcl_deepslate:tuff_polished")

# ---- mud family ----
add("mud", "mcl_mud:mud")
add("packed_mud", "mcl_mud:packed_mud")
add("mud_bricks", "mcl_mud:mud_bricks")
add("muddy_mangrove_roots", "mcl_mangrove:mangrove_mud_roots")

# ---- blackstone / basalt ----
add("blackstone", "mcl_blackstone:blackstone")
add("gilded_blackstone", "mcl_blackstone:blackstone_gilded")
add("polished_blackstone", "mcl_blackstone:blackstone_polished")
add("polished_blackstone_bricks", "mcl_blackstone:blackstone_brick_polished")
add("cracked_polished_blackstone_bricks", "mcl_blackstone:blackstone_brick_polished_cracked")
add("chiseled_polished_blackstone", "mcl_blackstone:blackstone_chiseled_polished")
add("basalt", "mcl_blackstone:basalt")
add("smooth_basalt", "mcl_blackstone:basalt_smooth")
add("polished_basalt", "mcl_blackstone:basalt_polished")

# ---- amethyst ----
add("amethyst_block", "mcl_amethyst:amethyst_block")
add("budding_amethyst", "mcl_amethyst:budding_amethyst_block")
add("amethyst_cluster", "mcl_amethyst:amethyst_cluster")
add("large_amethyst_bud", "mcl_amethyst:large_amethyst_bud")
add("medium_amethyst_bud", "mcl_amethyst:medium_amethyst_bud")
add("small_amethyst_bud", "mcl_amethyst:small_amethyst_bud")
add("calcite", "mcl_amethyst:calcite")
add("tinted_glass", "mcl_amethyst:tinted_glass")

# ---- sculk ----
add("sculk", "mcl_sculk:sculk")
add("sculk_vein", "mcl_sculk:vein")
add("sculk_catalyst", "mcl_sculk:catalyst")
add("sculk_sensor", "mcl_sculk:sculk")
add("calibrated_sculk_sensor", "mcl_sculk:sculk")
add("sculk_shrieker", "mcl_sculk:sculk")

# ---- end ----
add("end_stone", "mcl_end:end_stone")
add("end_stone_bricks", "mcl_end:end_bricks")
add("purpur_block", "mcl_end:purpur_block")
add("purpur_pillar", "mcl_end:purpur_pillar")
add("end_rod", "mcl_end:end_rod")
add("chorus_plant", "mcl_end:chorus_plant")
add("chorus_flower", "mcl_end:chorus_flower")
add("dragon_egg", "mcl_end:dragon_egg")
add("end_gateway", "mcl_portals:portal_gateway")
add("jigsaw", "mcl_levelgen:jigsaw_block")
add("structure_block", "mcl_levelgen:structure_block_save")
add("decorated_pot", "mcl_pottery_sherds:pot")
add("command_block", "mcl_commandblock:commandblock_off")
add("chain_command_block", "mcl_commandblock:commandblock_off")
add("repeating_command_block", "mcl_commandblock:commandblock_off")
add("resin_clump", "mcl_pale_oak:block_of_resin")
add("end_portal_frame", "mcl_portals:end_portal_frame")
add("end_portal", "mcl_portals:portal_end")

# ---- nether plants ----
add("nether_wart_block", "mcl_nether:nether_wart_block")
add("warped_wart_block", "mcl_crimson:warped_wart_block")
add("nether_sprouts", "mcl_crimson:nether_sprouts")
add("shroomlight", "mcl_crimson:shroomlight")
add("crimson_fungus", "mcl_crimson:crimson_fungus")
add("warped_fungus", "mcl_crimson:warped_fungus")
add("crimson_roots", "mcl_crimson:crimson_roots")
add("warped_roots", "mcl_crimson:warped_roots")
add("crimson_nylium", "mcl_crimson:crimson_nylium")
add("warped_nylium", "mcl_crimson:warped_nylium")
add("weeping_vines", "mcl_crimson:weeping_vines")
add("twisting_vines", "mcl_crimson:twisting_vines")
add("soul_fire", "mcl_blackstone:soul_fire")
add("soul_torch", "mcl_blackstone:soul_torch")

# ---- copper ----
add("copper_block", "mcl_copper:block")
add("exposed_copper", "mcl_copper:block_exposed")
add("weathered_copper", "mcl_copper:block_weathered")
add("oxidized_copper", "mcl_copper:block_oxidized")
add("cut_copper", "mcl_copper:block_cut")
add("exposed_cut_copper", "mcl_copper:block_exposed_cut")
add("weathered_cut_copper", "mcl_copper:block_weathered_cut")
add("oxidized_cut_copper", "mcl_copper:block_oxidized_cut")
add("chiseled_copper", "mcl_copper:block_chiseled")
add("copper_bulb", "mcl_copper:bulb_off")
add("raw_copper_block", "mcl_copper:block_raw")
add("raw_iron_block", "mcl_raw_ores:raw_iron_block")
add("raw_gold_block", "mcl_raw_ores:raw_gold_block")
add("copper_door", "mcl_copper:door_b_1")
add("copper_door|lower", "mcl_copper:door_b_1")
add("copper_door|upper", "mcl_copper:door_t_1")
add("copper_door|lower|open", "mcl_copper:door_b_2")
add("copper_door|upper|open", "mcl_copper:door_t_2")
add("copper_trapdoor", "mcl_copper:trapdoor")
add("copper_bars", "mcl_panes:copper_bar")
add("copper_grate", "mcl_copper:block")
add("exposed_copper_grate", "mcl_copper:block_exposed")
add("weathered_copper_grate", "mcl_copper:block_weathered")
add("oxidized_copper_grate", "mcl_copper:block_oxidized")
add("copper_chain", "mcl_lanterns:copper_chain")
add("copper_torch", "mcl_copper:copper_torch")
# waxed copper -> same visual block
for waxed, target in [("waxed_copper_block", "mcl_copper:block"),
                      ("waxed_exposed_copper", "mcl_copper:block_exposed"),
                      ("waxed_weathered_copper", "mcl_copper:block_weathered"),
                      ("waxed_oxidized_copper", "mcl_copper:block_oxidized"),
                      ("waxed_cut_copper", "mcl_copper:block_cut"),
                      ("waxed_exposed_cut_copper", "mcl_copper:block_exposed_cut"),
                      ("waxed_weathered_cut_copper", "mcl_copper:block_weathered_cut"),
                      ("waxed_oxidized_cut_copper", "mcl_copper:block_oxidized_cut"),
                      ("waxed_chiseled_copper", "mcl_copper:block_chiseled"),
                      ("waxed_copper_bulb", "mcl_copper:bulb_off"),
                      ("waxed_copper_door", "mcl_copper:door_t_1"),
                      ("waxed_copper_trapdoor", "mcl_copper:trapdoor"),
                      ("waxed_copper_bars", "mcl_panes:copper_bar"),
                      ("waxed_copper_grate", "mcl_copper:block"),
                      ("waxed_exposed_copper_grate", "mcl_copper:block_exposed"),
                      ("waxed_weathered_copper_grate", "mcl_copper:block_weathered"),
                      ("waxed_oxidized_copper_grate", "mcl_copper:block_oxidized")]:
    add(waxed, target)

# ---- utility / furniture ----
add("barrel", "mcl_barrels:barrel_closed")
add("lectern", "mcl_lectern:lectern")
add("bamboo", "mcl_bamboo:bamboo_big")
add("scaffolding", "mcl_bamboo:scaffolding")
add("crafting_table", "mcl_crafting_table:crafting_table")
add("furnace", "mcl_furnaces:furnace")
add("blast_furnace", "mcl_blast_furnace:blast_furnace")
add("smoker", "mcl_smoker:smoker")
add("chest", "mcl_chests:chest")
add("trapped_chest", "mcl_chests:trapped_chest")
add("ender_chest", "mcl_chests:ender_chest")
add("jukebox", "mcl_jukebox:jukebox")
add("noteblock", "mcl_noteblock:noteblock")
add("spawner", "mcl_mobspawners:spawner")
add("trial_spawner", "mcl_trial_spawners:trialspawner")
add("vault", "mcl_vaults:vault")
add("beacon", "mcl_beacons:beacon")
add("anvil", "mcl_anvils:anvil")
add("chipped_anvil", "mcl_anvils:anvil_damage_1")
add("damaged_anvil", "mcl_anvils:anvil_damage_2")
add("enchanting_table", "mcl_enchanting:table")
add("brewing_stand", "mcl_brewing:stand_000")
add("cauldron", "mcl_cauldrons:cauldron")
add("hopper", "mcl_hoppers:hopper")
add("redstone_lamp", "mcl_redstone_lamp:lamp_off")
add("daylight_detector", "mcl_daylight_detector:daylight_detector")
add("observer", "mcl_observers:observer_off")
add("redstone_wire", "mcl_redstone:redstone")
add("redstone_torch", "mcl_redstone_torch:redstone_torch_off")
add("lever", "mcl_lever:lever_off")
add("rail", "mcl_minecarts:rail")
add("golden_rail", "mcl_minecarts:golden_rail")
add("detector_rail", "mcl_minecarts:detector_rail")
add("activator_rail", "mcl_minecarts:activator_rail")
add("torch", "mcl_torches:torch")
add("ladder", "mcl_core:ladder")
add("vine", "mcl_core:vine")
add("glow_lichen", "mcl_core:glow_lichen")
add("lily_pad", "mcl_flowers:waterlily")
add("cactus", "mcl_core:cactus")
add("sugar_cane", "mcl_core:reeds")
add("mushroom_stem", "mcl_mushrooms:brown_mushroom_block_stem")
add("cake", "mcl_cake:cake")
add("candle", "mcl_candles:candle_1")
add("candle_cake", "mcl_candles:candle_cake")
add("attached_melon_stem", "mcl_farming:melontige_linked_b")
add("attached_pumpkin_stem", "mcl_farming:pumpkintige_linked_b")
add("big_dripleaf_stem", "mcl_lush_caves:dripleaf_big_stem")
add("bubble_column", "mcl_core:water_source")
add("crimson_stem", "mcl_trees:tree_crimson")
add("stripped_crimson_stem", "mcl_trees:stripped_crimson")
add("crimson_hyphae", "mcl_trees:bark_crimson")
add("stripped_crimson_hyphae", "mcl_trees:bark_stripped_crimson")
add("warped_stem", "mcl_trees:tree_warped")
add("stripped_warped_stem", "mcl_trees:stripped_warped")
add("warped_hyphae", "mcl_trees:bark_warped")
add("stripped_warped_hyphae", "mcl_trees:bark_stripped_warped")
add("brown_mushroom_block", "mcl_mushrooms:brown_mushroom_block_cap_111111")
add("red_mushroom_block", "mcl_mushrooms:red_mushroom_block_cap_111111")
add("pumpkin", "mcl_farming:pumpkin")
add("carved_pumpkin", "mcl_farming:pumpkin_face")
add("jack_o_lantern", "mcl_farming:pumpkin_face_light")
add("melon", "mcl_farming:melon")
add("farmland", "mcl_farming:soil")
add("composter", "mcl_composters:composter")
add("stonecutter", "mcl_stonecutter:stonecutter")
add("cartography_table", "mcl_cartography_table:cartography_table")
add("fletching_table", "mcl_fletching_table:fletching_table")
add("smithing_table", "mcl_smithing_table:table")
add("grindstone", "mcl_grindstone:grindstone")
add("loom", "mcl_loom:loom")
add("bell", "mcl_bells:bell")
add("lantern", "mcl_lanterns:lantern_floor")
add("soul_lantern", "mcl_lanterns:soul_lantern_floor")
add("chain", "mcl_lanterns:chain")
add("lightning_rod", "mcl_lightning_rods:rod")
add("target", "mcl_target:target_off")
add("lodestone", "mcl_compass:lodestone")
add("conduit", "mcl_conduits:conduit")
add("respawn_anchor", "mcl_beds:respawn_anchor")
add("campfire", "mcl_campfires:campfire")
add("soul_campfire", "mcl_campfires:soul_campfire")
add("beehive", "mcl_beehives:beehive")
add("bee_nest", "mcl_beehives:bee_nest")
add("sea_pickle", "mcl_ocean:sea_pickle_1_dirt")
add("cactus_flower", "mcl_core:cactus_flower")
add("flower_pot", "mcl_flowerpots:flower_pot")
add("dried_kelp", "mcl_ocean:dried_kelp_block")
add("kelp", "mcl_ocean:kelp_dirt")
add("seagrass", "mcl_ocean:seagrass_dirt")
add("tall_seagrass", "mcl_ocean:seagrass_dirt")
add("fire", "mcl_fire:fire")
add("water", "mcl_core:water_source")
add("lava", "mcl_core:lava_source")
add("powder_snow", "mcl_core:snow")
add("dispenser", "mcl_dispensers:dispenser")
add("dropper", "mcl_dispensers:dropper")
add("comparator", "mcl_comparators:comparator_off_comp")
add("repeater", "mcl_repeaters:repeater_off_1")
add("piston", "mcl_pistons:piston_off")
add("sticky_piston", "mcl_pistons:piston_sticky_off")
add("note_block", "mcl_noteblock:noteblock")
add("mangrove_roots", "mcl_mangrove:mangrove_roots")
add("nether_portal", "mcl_portals:portal")
add("nether_wart", "mcl_nether:nether_wart_0")
add("nether_brick_fence", "mcl_fences:nether_brick_fence")
add("kelp_plant", "mcl_ocean:kelp_dirt")
add("item_frame", "mcl_itemframes:frame")
add("glow_item_frame", "mcl_itemframes:glow_frame")
add("iron_chain", "mcl_lanterns:chain")
add("stone_pressure_plate", "mcl_pressureplates:pressure_plate_stone_off")
add("polished_blackstone_pressure_plate", "mcl_pressureplates:pressure_plate_polished_blackstone_off")
add("heavy_core", "mcl_tools:heavy_core")
add("golden_dandelion", "mcl_flowers:dandelion")
add("polished_blackstone_button", "mcl_buttons:button_polished_blackstone_off")
add("piglin_head", "mcl_heads:piglin")
add("piglin_wall_head", "mcl_heads:piglin")
add("piston_head", "mcl_pistons:piston_off")
add("lava_cauldron", "mcl_cauldrons:cauldron")
add("exposed_lightning_rod", "mcl_lightning_rods:rod")
add("weathered_lightning_rod", "mcl_lightning_rods:rod")
add("oxidized_lightning_rod", "mcl_lightning_rods:rod")
add("exposed_copper_door", "mcl_copper:door_exposed_t_1")
add("weathered_copper_door", "mcl_copper:door_weathered_t_1")
add("oxidized_copper_door", "mcl_copper:door_oxidized_t_1")
add("exposed_copper_trapdoor", "mcl_copper:trapdoor_exposed")
add("weathered_copper_trapdoor", "mcl_copper:trapdoor_weathered")
add("oxidized_copper_trapdoor", "mcl_copper:trapdoor_oxidized")
add("exposed_copper_bars", "mcl_panes:copper_bar_exposed")
add("weathered_copper_bars", "mcl_panes:copper_bar_weathered")
add("oxidized_copper_bars", "mcl_panes:copper_bar_oxidized")
add("exposed_chiseled_copper", "mcl_copper:block_exposed_chiseled")
add("weathered_chiseled_copper", "mcl_copper:block_weathered_chiseled")
add("oxidized_chiseled_copper", "mcl_copper:block_oxidized_chiseled")
add("exposed_copper_bulb", "mcl_copper:bulb_exposed_off")
add("weathered_copper_bulb", "mcl_copper:bulb_weathered_off")
add("oxidized_copper_bulb", "mcl_copper:bulb_oxidized_off")
add("copper_lantern", "mcl_lanterns:copper_lantern_floor")
add("exposed_copper_lantern", "mcl_lanterns:copper_lantern_exposed_floor")
add("weathered_copper_lantern", "mcl_lanterns:copper_lantern_weathered_floor")
add("oxidized_copper_lantern", "mcl_lanterns:copper_lantern_oxidized_floor")
add("copper_wall_torch", "mcl_copper:copper_torch")
add("exposed_copper_chain", "mcl_lanterns:copper_chain_exposed")
add("weathered_copper_chain", "mcl_lanterns:copper_chain_weathered")
add("oxidized_copper_chain", "mcl_lanterns:copper_chain_oxidized")
add("bush", "mcl_flowers:bush")
add("firefly_bush", "mcl_flowers:firefly_bush")
add("leaf_litter", "mcl_flowers:leaf_litter_1")
add("short_dry_grass", "mcl_flowers:short_dry_grass")
add("tall_dry_grass", "mcl_flowers:tall_dry_grass")
add("creaking_heart", "mcl_trees:tree_pale_oak")
# skulls / heads
for head, mcl in [("skeleton_skull", "mcl_heads:skeleton"),
                  ("wither_skeleton_skull", "mcl_heads:wither_skeleton"),
                  ("zombie_head", "mcl_heads:zombie"),
                  ("player_head", "mcl_heads:steve"),
                  ("creeper_head", "mcl_heads:creeper"),
                  ("dragon_head", "mcl_heads:dragon")]:
    add(head, mcl)
    add(head.replace("_head", "_wall_head"), mcl)
    add(head.replace("_skull", "_wall_skull"), mcl)

# ---- coral ----
for base, cl in [("tube", "tube"), ("brain", "brain"), ("bubble", "bubble"),
                 ("fire", "fire"), ("horn", "horn")]:
    add(f"{base}_coral", f"mcl_ocean:{cl}_coral")
    add(f"{base}_coral_block", f"mcl_ocean:{cl}_coral_block")
    add(f"{base}_coral_fan", f"mcl_ocean:{cl}_coral_fan")
    add(f"dead_{base}_coral", f"mcl_ocean:dead_{cl}_coral")
    add(f"dead_{base}_coral_block", f"mcl_ocean:dead_{cl}_coral_block")
    add(f"dead_{base}_coral_fan", f"mcl_ocean:dead_{cl}_coral_fan")

# ---- flowers / plants ----
add("dandelion", "mcl_flowers:dandelion")
add("poppy", "mcl_flowers:poppy")
add("blue_orchid", "mcl_flowers:blue_orchid")
add("allium", "mcl_flowers:allium")
add("azure_bluet", "mcl_flowers:azure_bluet")
add("red_tulip", "mcl_flowers:tulip_red")
add("orange_tulip", "mcl_flowers:tulip_orange")
add("white_tulip", "mcl_flowers:tulip_white")
add("pink_tulip", "mcl_flowers:tulip_pink")
add("oxeye_daisy", "mcl_flowers:oxeye_daisy")
add("cornflower", "mcl_flowers:cornflower")
add("lily_of_the_valley", "mcl_flowers:lily_of_the_valley")
add("wither_rose", "mcl_flowers:wither_rose")
add("torchflower", "mcl_flowers:poppy")
add("short_grass", "mcl_flowers:tallgrass")
add("grass", "mcl_flowers:tallgrass")
add("fern", "mcl_flowers:fern")
add("tall_grass", "mcl_flowers:double_grass")
add("large_fern", "mcl_flowers:double_fern")
add("sunflower", "mcl_flowers:sunflower")
add("lilac", "mcl_flowers:lilac")
add("rose_bush", "mcl_flowers:rose_bush")
add("peony", "mcl_flowers:peony")
add("pink_petals", "mcl_flowers:pink_petals_1")
add("wildflowers", "mcl_flowers:wildflowers_1")
add("brown_mushroom", "mcl_mushrooms:mushroom_brown")
add("red_mushroom", "mcl_mushrooms:mushroom_red")
add("wheat", "mcl_farming:wheat_1")
add("carrots", "mcl_farming:carrot_1")
add("potatoes", "mcl_farming:potato_1")
add("beetroots", "mcl_farming:beetroot_1")
add("melon_stem", "mcl_farming:melontige_unconnect")
add("pumpkin_stem", "mcl_farming:pumpkintige_unconnect")
add("cocoa", "mcl_cocoas:cocoa_0")
add("sweet_berry_bush", "mcl_farming:sweet_berry_bush_0")
add("bamboo_sapling", "mcl_bamboo:bamboo_shoot")

# ---- lush caves ----
add("azalea", "mcl_lush_caves:azalea")
add("flowering_azalea", "mcl_lush_caves:azalea_flowering")
add("azalea_leaves", "mcl_trees:leaves_azalea")
add("flowering_azalea_leaves", "mcl_trees:leaves_azalea_flowering")
add("moss_block", "mcl_lush_caves:moss")
add("moss_carpet", "mcl_lush_caves:moss_carpet")
add("hanging_roots", "mcl_lush_caves:hanging_roots")
add("spore_blossom", "mcl_lush_caves:spore_blossom")
add("cave_vines", "mcl_lush_caves:cave_vines")
add("cave_vines_plant", "mcl_lush_caves:cave_vines")
add("big_dripleaf", "mcl_lush_caves:dripleaf_big")
add("small_dripleaf", "mcl_lush_caves:dripleaf_small")
add("dripleaf", "mcl_lush_caves:dripleaf_big")
add("pointed_dripstone", "mcl_dripstone:dripstone_top_tip")
add("dripstone_block", "mcl_dripstone:dripstone_block")
# Pointed dripstone: MC `vertical_direction` (up/down) + `thickness`
# (tip/frustum/middle/base).  The converter appends |<dir>|<thickness>.
# up = stalagmite (mcl dripstone_bottom_*), down = stalactite (top_*).
for d, mcl_d in (("up", "bottom"), ("down", "top")):
    for t in ("tip", "frustum", "middle", "base"):
        add(f"pointed_dripstone|{d}|{t}", f"mcl_dripstone:dripstone_{mcl_d}_{t}")

# ---- pale garden (1.21.4) ----
add("pale_moss_block", "mcl_pale_oak:pale_moss")
add("pale_moss_carpet", "mcl_pale_oak:pale_moss_carpet")
add("pale_hanging_moss", "mcl_pale_oak:hanging_moss")
add("resin_block", "mcl_pale_oak:block_of_resin")
add("resin_bricks", "mcl_pale_oak:resin_brick_block")
add("chiseled_resin_bricks", "mcl_pale_oak:chiseled_resin_brick")
add("open_eyeblossom", "mcl_flowers:eyeblossom_open")
add("closed_eyeblossom", "mcl_flowers:eyeblossom")
add("creaking_heart", "mcl_trees:tree_pale_oak")

# ---- wood specials (mangrove propagule, bamboo blocks) ----
add("mangrove_propagule", "mcl_mangrove:propagule")
add("bamboo_block", "mcl_trees:tree_bamboo")
add("stripped_bamboo_block", "mcl_trees:stripped_bamboo")
add("bamboo_planks", "mcl_trees:wood_bamboo")
add("bamboo_mosaic", "mcl_bamboo:bamboo_mosaic")
add("bamboo_mosaic_stairs", "mcl_stairs:stair_bamboo_mosaic")
add("bamboo_mosaic_slab", "mcl_stairs:slab_bamboo_mosaic")
add("heavy_weighted_pressure_plate", "mcl_pressureplates:pressure_plate_heavy_off")
add("light_weighted_pressure_plate", "mcl_pressureplates:pressure_plate_light_off")
add("powered_rail", "mcl_minecarts:golden_rail")
add("redstone_wall_torch", "mcl_redstone_torch:redstone_torch_off_wall")
add("soul_wall_torch", "mcl_blackstone:soul_torch")
add("stone_button", "mcl_buttons:button_stone_off")
add("smooth_stone_slab", "mcl_stairs:slab_stone")
add("structure_void", "air")
add("powder_snow_cauldron", "mcl_cauldrons:cauldron")
add("moving_piston", "mcl_pistons:piston_off")
add("wall_torch", "mcl_torches:torch_wall")
add("water_cauldron", "mcl_cauldrons:cauldron")
add("twisting_vines_plant", "mcl_crimson:twisting_vines")
add("weeping_vines_plant", "mcl_crimson:weeping_vines")
add("petrified_oak_slab", "mcl_stairs:slab_oak")
add("waxed_copper_chain", "mcl_lanterns:copper_chain")
add("waxed_exposed_copper_chain", "mcl_lanterns:copper_chain_exposed")
add("waxed_weathered_copper_chain", "mcl_lanterns:copper_chain_weathered")
add("waxed_oxidized_copper_chain", "mcl_lanterns:copper_chain_oxidized")
add("waxed_copper_lantern", "mcl_lanterns:copper_lantern_floor")
add("waxed_exposed_copper_lantern", "mcl_lanterns:copper_lantern_exposed_floor")
add("waxed_weathered_copper_lantern", "mcl_lanterns:copper_lantern_weathered_floor")
add("waxed_oxidized_copper_lantern", "mcl_lanterns:copper_lantern_oxidized_floor")
add("waxed_lightning_rod", "mcl_lightning_rods:rod")
add("waxed_exposed_lightning_rod", "mcl_lightning_rods:rod")
add("waxed_weathered_lightning_rod", "mcl_lightning_rods:rod")
add("waxed_oxidized_lightning_rod", "mcl_lightning_rods:rod")
add("waxed_exposed_chiseled_copper", "mcl_copper:block_exposed_chiseled")
add("waxed_weathered_chiseled_copper", "mcl_copper:block_weathered_chiseled")
add("waxed_oxidized_chiseled_copper", "mcl_copper:block_oxidized_chiseled")
add("waxed_exposed_copper_bars", "mcl_panes:copper_bar_exposed")
add("waxed_weathered_copper_bars", "mcl_panes:copper_bar_weathered")
add("waxed_oxidized_copper_bars", "mcl_panes:copper_bar_oxidized")
add("waxed_exposed_copper_bulb", "mcl_copper:bulb_exposed")
add("waxed_weathered_copper_bulb", "mcl_copper:bulb_weathered")
add("waxed_oxidized_copper_bulb", "mcl_copper:bulb_oxidized")
add("waxed_exposed_copper_door", "mcl_copper:door_exposed_t_1")
add("waxed_weathered_copper_door", "mcl_copper:door_weathered_t_1")
add("waxed_oxidized_copper_door", "mcl_copper:door_oxidized_t_1")
add("waxed_exposed_copper_trapdoor", "mcl_copper:trapdoor_exposed")
add("waxed_weathered_copper_trapdoor", "mcl_copper:trapdoor_weathered")
add("waxed_oxidized_copper_trapdoor", "mcl_copper:trapdoor_oxidized")

# ---------------------------------------------------------------------------
# 3. Families
# ---------------------------------------------------------------------------
# MC wood name -> MCL wood name
WOOD_ALIAS = {"oak": "oak", "spruce": "spruce", "birch": "birch",
              "jungle": "jungle", "acacia": "acacia", "dark_oak": "dark_oak",
              "mangrove": "mangrove", "cherry": "cherry_blossom",
              "bamboo": "bamboo", "crimson": "crimson",
              "warped": "warped", "pale_oak": "pale_oak"}

# MC suffix -> template, {w} = MCL wood name
WOOD_FAMILIES = {
    "planks": "mcl_trees:wood_{w}",
    "log": "mcl_trees:tree_{w}",
    "stripped_log": "mcl_trees:stripped_{w}",
    "wood": "mcl_trees:bark_{w}",
    "stripped_wood": "mcl_trees:bark_stripped_{w}",
    "leaves": "mcl_trees:leaves_{w}",
    "sapling": "mcl_trees:sapling_{w}",
    "fence": "mcl_fences:{w}_fence",
    "fence_gate": "mcl_fences:{w}_fence_gate",
    "door": "mcl_doors:door_{w}",
    "trapdoor": "mcl_doors:trapdoor_{w}",
    "stairs": "mcl_stairs:stair_{w}",
    "slab": "mcl_stairs:slab_{w}",
    "button": "mcl_buttons:button_{w}_off",
    "pressure_plate": "mcl_pressureplates:pressure_plate_{w}_off",
    "sign": "mcl_signs:standing_sign_{w}",
    "wall_sign": "mcl_signs:wall_sign_{w}",
    "hanging_sign": "mcl_signs:hanging_sign_{w}",
    "wall_hanging_sign": "mcl_signs:hanging_sign_wall_{w}",
}

# MC color -> MCL color
COLOR_ALIAS = {"white": "white", "light_gray": "silver", "gray": "grey",
               "black": "black", "brown": "brown", "red": "red",
               "orange": "orange", "yellow": "yellow", "lime": "lime",
               "green": "green", "cyan": "cyan", "light_blue": "light_blue",
               "blue": "blue", "purple": "purple", "magenta": "magenta",
               "pink": "pink"}

# MC color-block suffix -> template, {c} = MCL color
COLOR_FAMILIES = {
    "wool": "mcl_wool:{c}",
    "carpet": "mcl_wool:{c}_carpet",
    "terracotta": "mcl_colorblocks:hardened_clay_{c}",
    "glazed_terracotta": "mcl_colorblocks:glazed_terracotta_{c}",
    "concrete": "mcl_colorblocks:concrete_{c}",
    "concrete_powder": "mcl_colorblocks:concrete_powder_{c}",
    "stained_glass": "mcl_core:glass_{c}",
    "stained_glass_pane": "mcl_panes:pane_{c}",
    "candle": "mcl_candles:candle_{c}",
}

# MC block -> stair/slab subname (mcl_stairs)
STAIR_MAP = {
    "stone_stairs": "stone_rough", "stone_slab": "stone",
    "cobblestone_stairs": "cobble", "cobblestone_slab": "cobble",
    "mossy_cobblestone_stairs": "mossycobble", "mossy_cobblestone_slab": "mossycobble",
    "stone_brick_stairs": "stonebrick", "stone_brick_slab": "stonebrick",
    "mossy_stone_brick_stairs": "stonebrickmossy", "mossy_stone_brick_slab": "stonebrickmossy",
    "cracked_stone_brick_stairs": "stonebrickcracked", "cracked_stone_brick_slab": "stonebrickcracked",
    "sandstone_stairs": "sandstone", "sandstone_slab": "sandstone",
    "smooth_sandstone_stairs": "sandstonesmooth2", "smooth_sandstone_slab": "sandstonesmooth2",
    "cut_sandstone_stairs": "sandstonesmooth", "cut_sandstone_slab": "sandstonesmooth",
    "red_sandstone_stairs": "redsandstone", "red_sandstone_slab": "redsandstone",
    "smooth_red_sandstone_stairs": "redsandstonesmooth2", "smooth_red_sandstone_slab": "redsandstonesmooth2",
    "cut_red_sandstone_stairs": "redsandstonesmooth", "cut_red_sandstone_slab": "redsandstonesmooth",
    "granite_stairs": "granite", "granite_slab": "granite",
    "polished_granite_stairs": "granite_smooth", "polished_granite_slab": "granite_smooth",
    "diorite_stairs": "diorite", "diorite_slab": "diorite",
    "polished_diorite_stairs": "diorite_smooth", "polished_diorite_slab": "diorite_smooth",
    "andesite_stairs": "andesite", "andesite_slab": "andesite",
    "polished_andesite_stairs": "andesite_smooth", "polished_andesite_slab": "andesite_smooth",
    "brick_stairs": "brick_block", "brick_slab": "brick_block",
    "quartz_stairs": "quartzblock", "quartz_slab": "quartzblock",
    "smooth_quartz_stairs": "quartz_smooth", "smooth_quartz_slab": "quartz_smooth",
    "nether_brick_stairs": "nether_brick", "nether_brick_slab": "nether_brick",
    "red_nether_brick_stairs": "red_nether_brick", "red_nether_brick_slab": "red_nether_brick",
    "end_stone_brick_stairs": "end_bricks", "end_stone_brick_slab": "end_bricks",
    "purpur_stairs": "purpur_block", "purpur_slab": "purpur_block",
    "prismarine_stairs": "prismarine", "prismarine_slab": "prismarine",
    "prismarine_brick_stairs": "prismarine_brick", "prismarine_brick_slab": "prismarine_brick",
    "dark_prismarine_stairs": "prismarine_dark", "dark_prismarine_slab": "prismarine_dark",
    "blackstone_stairs": "blackstone", "blackstone_slab": "blackstone",
    "polished_blackstone_stairs": "blackstone_polished", "polished_blackstone_slab": "blackstone_polished",
    "polished_blackstone_brick_stairs": "blackstone_brick_polished", "polished_blackstone_brick_slab": "blackstone_brick_polished",
    "cobbled_deepslate_stairs": "deepslate_cobbled", "cobbled_deepslate_slab": "deepslate_cobbled",
    "polished_deepslate_stairs": "deepslate_polished", "polished_deepslate_slab": "deepslate_polished",
    "deepslate_brick_stairs": "deepslate_bricks", "deepslate_brick_slab": "deepslate_bricks",
    "deepslate_tile_stairs": "deepslate_tiles", "deepslate_tile_slab": "deepslate_tiles",
    "polished_tuff_stairs": "tuff_polished", "polished_tuff_slab": "tuff_polished",
    "tuff_brick_stairs": "tuff_bricks", "tuff_brick_slab": "tuff_bricks",
    "mud_brick_stairs": "mud_brick", "mud_brick_slab": "mud_brick",
    "cut_copper_stairs": "copper_cut", "cut_copper_slab": "copper_cut",
    "exposed_cut_copper_stairs": "copper_exposed_cut", "exposed_cut_copper_slab": "copper_exposed_cut",
    "weathered_cut_copper_stairs": "copper_weathered_cut", "weathered_cut_copper_slab": "copper_weathered_cut",
    "oxidized_cut_copper_stairs": "copper_oxidized_cut", "oxidized_cut_copper_slab": "copper_oxidized_cut",
    "resin_brick_stairs": "resin_brick", "resin_brick_slab": "resin_brick",
}
# Mineclonia has no plain tuff stairs/slabs: use the plain tuff block
STAIR_MAP.pop("tuff_stairs", None)
STAIR_MAP.pop("tuff_slab", None)
add("tuff_stairs", "mcl_deepslate:tuff")
add("tuff_slab", "mcl_deepslate:tuff")

# mud brick stairs/slabs map to mcl_stairs:stair_mud_brick / slab_mud_brick
for w in ["waxed_cut_copper", "waxed_exposed_cut_copper",
          "waxed_weathered_cut_copper", "waxed_oxidized_cut_copper"]:
    STAIR_MAP[f"{w}_stairs"] = STAIR_MAP[w.replace("waxed_", "") + "_stairs"]
    STAIR_MAP[f"{w}_slab"] = STAIR_MAP[w.replace("waxed_", "") + "_slab"]

# MC block -> wall material (mcl_walls / mcl_deepslate:...wall)
WALL_MAP = {
    "cobblestone_wall": "mcl_walls:cobble",
    "mossy_cobblestone_wall": "mcl_walls:mossycobble",
    "stone_brick_wall": "mcl_walls:stonebrick",
    "mossy_stone_brick_wall": "mcl_walls:stonebrickmossy",
    "cracked_stone_brick_wall": "mcl_walls:stonebrick",
    "andesite_wall": "mcl_walls:andesite",
    "granite_wall": "mcl_walls:granite",
    "diorite_wall": "mcl_walls:diorite",
    "brick_wall": "mcl_walls:brick",
    "sandstone_wall": "mcl_walls:sandstone",
    "red_sandstone_wall": "mcl_walls:redsandstone",
    "prismarine_wall": "mcl_walls:prismarine",
    "nether_brick_wall": "mcl_walls:netherbrick",
    "red_nether_brick_wall": "mcl_walls:rednetherbrick",
    "end_stone_brick_wall": "mcl_walls:endbricks",
    "blackstone_wall": "mcl_blackstone:wall",
    "polished_blackstone_wall": "mcl_blackstone:polishedwall",
    "polished_blackstone_brick_wall": "mcl_blackstone:polishedbrickwall",
    "cobbled_deepslate_wall": "mcl_deepslate:deepslatecobbledwall",
    "polished_deepslate_wall": "mcl_deepslate:deepslatepolishedwall",
    "deepslate_brick_wall": "mcl_deepslate:deepslatebrickswall",
    "deepslate_tile_wall": "mcl_deepslate:deepslatetileswall",
    "tuff_wall": "mcl_deepslate:tuff",
    "polished_tuff_wall": "mcl_deepslate:tuffpolishedwall",
    "tuff_brick_wall": "mcl_deepslate:tuffbrickswall",
    "mud_brick_wall": "mcl_walls:mudbrick",
    "resin_brick_wall": "mcl_pale_oak:resin_brick_wall",
}

# infested (silverfish) blocks -> the plain block
for inf in ["infested_stone", "infested_cobblestone", "infested_stone_bricks",
            "infested_mossy_stone_bricks", "infested_cracked_stone_bricks",
            "infested_chiseled_stone_bricks"]:
    add(inf, D.get(inf.replace("infested_", ""), "mcl_core:stone"))

# potted plants -> plain flower pot (plant content is an entity)
import re as _re
for _b in list(MC_BLOCKS):
    if _b.startswith("potted_"):
        add(_b, "mcl_flowerpots:flower_pot")

# coral wall fans
for t in ["tube", "brain", "bubble", "fire", "horn"]:
    add(f"{t}_coral_wall_fan", f"mcl_ocean:{t}_coral_fan")
    add(f"dead_{t}_coral_wall_fan", f"mcl_ocean:dead_{t}_coral_fan")

# terracotta base (no color)
add("terracotta", "mcl_colorblocks:hardened_clay")

# shulker boxes (Mineclonia color names differ from MC)
SHULKER = {"white": "white", "orange": "orange", "magenta": "magenta",
           "light_blue": "lightblue", "yellow": "yellow", "lime": "green",
           "pink": "pink", "gray": "dark_grey", "light_gray": "grey",
           "cyan": "cyan", "purple": "violet", "blue": "blue",
           "brown": "brown", "green": "dark_green", "red": "red",
           "black": "black"}
for mc_c, mcl_c in SHULKER.items():
    add(f"{mc_c}_shulker_box", f"mcl_chests:{mcl_c}_shulker_box")
# undyed shulker box -> Mineclonia's canonical (violet)
add("shulker_box", "mcl_chests:violet_shulker_box")

# Minecraft has 16 colored banner block names, while Mineclonia uses one
# node for each placement. The base color is stored in the converted banner
# item metadata; the hanging node's wallmounted orientation remains param2.
for c in COLOR_ALIAS:
    add(f"{c}_banner", "mcl_banners:standing_banner")
    add(f"{c}_wall_banner", "mcl_banners:hanging_banner")
    # Beds: MC `part` state picks the half.  The converter appends
    # |head (pillow, one node further from the placer -> mcl _top) or
    # |foot (where the player stands -> mcl _bottom).
    add(f"{c}_bed", f"mcl_beds:bed_{COLOR_ALIAS[c]}_bottom")
    add(f"{c}_bed|head", f"mcl_beds:bed_{COLOR_ALIAS[c]}_top")
    add(f"{c}_bed|foot", f"mcl_beds:bed_{COLOR_ALIAS[c]}_bottom")

# glass panes (colorless) + iron bars
add("glass_pane", "mcl_panes:pane_white")
add("iron_bars", "mcl_panes:bar")
add("iron_door", "mcl_doors:iron_door_b_1")
add("iron_door|lower", "mcl_doors:iron_door_b_1")
add("iron_door|upper", "mcl_doors:iron_door_t_1")
add("iron_door|lower|open", "mcl_doors:iron_door_b_2")
add("iron_door|upper|open", "mcl_doors:iron_door_t_2")
add("iron_trapdoor", "mcl_doors:iron_trapdoor")
add("iron_trapdoor|open", "mcl_doors:iron_trapdoor_open")

add("suspicious_gravel", "mcl_sus_nodes:gravel")
add("suspicious_sand", "mcl_sus_nodes:sand")

# Light block: MC `level` state (0-15) -> mcl_core:light_0..14.
# Mineclonia registers light_0..light_14 (core.LIGHT_MAX = 14), so
# level 15 is clamped to 14.  The converter appends |<level>.
for n in range(15):
    add(f"light|{n}", f"mcl_core:light_{n}")
add("light", "mcl_core:light_14")

# ---------------------------------------------------------------------------
# 4. Assemble full mapping
# ---------------------------------------------------------------------------
FULL = dict(D)

# Stair corner variants for blocks added directly above (not part of
# STAIR_MAP / wood families).
add_stair_shapes("bamboo_mosaic_stairs", "mcl_stairs:stair_bamboo_mosaic")
# tuff_stairs has no Mineclonia stair node -- keep every shape as plain tuff
# so the threaded state names still resolve.
for sh in ("straight", "outer_left", "outer_right", "inner_left", "inner_right"):
    FULL[f"tuff_stairs|{sh}"] = "mcl_deepslate:tuff"

# Stairs: the converter threads the MC `shape` block state (|straight /
def fill_wood():
    for mc_w, mcl_w in WOOD_ALIAS.items():
        for suffix, templ in WOOD_FAMILIES.items():
            if suffix in ("stripped_log", "stripped_wood"):
                # MC names these "stripped_<wood>_log" / "stripped_<wood>_wood"
                key = f"stripped_{mc_w}_" + suffix.split("_")[1]
            else:
                key = f"{mc_w}_{suffix}"
            if key in FULL:
                continue
            if mcl_w == "bamboo" and suffix in ("sapling", "leaves", "wood", "stripped_wood"):
                continue
            if mcl_w in ("crimson", "warped") and suffix in ("leaves", "sapling"):
                continue
            if mcl_w == "mangrove" and suffix == "sapling":
                continue
            if suffix == "door":
                # Doors have separate bottom/top and closed/open nodes.
                # The converter appends |lower / |upper and |open from
                # the Minecraft block state.
                base = f"mcl_doors:door_{mcl_w}"
                FULL[key] = base + "_b_1"
                FULL[key + "|lower"] = base + "_b_1"
                FULL[key + "|upper"] = base + "_t_1"
                FULL[key + "|lower|open"] = base + "_b_2"
                FULL[key + "|upper|open"] = base + "_t_2"
            elif suffix == "stairs":
                base = templ.replace("{w}", mcl_w)
                FULL[key] = base
                add_stair_shapes(key, base)
            elif suffix == "trapdoor":
                base = templ.replace("{w}", mcl_w)
                FULL[key] = base
                FULL[key + "|open"] = base + "_open"
            else:
                FULL[key] = templ.replace("{w}", mcl_w)

def fill_colors():
    for mc_c, mcl_c in COLOR_ALIAS.items():
        for suffix, templ in COLOR_FAMILIES.items():
            key = f"{mc_c}_{suffix}"
            if key in FULL:
                continue
            FULL[key] = templ.replace("{c}", mcl_c)
    # Candles: same node for every color -- the color lives in param2
    # (palette_index).  The converter appends |<count> and |lit from the
    # block states, so emit all 16 colors x 4 counts x lit/unlit variants.
    for mc_c in COLOR_ALIAS:
        FULL[f"{mc_c}_candle"] = "mcl_candles:candle_1"
        FULL[f"{mc_c}_candle_cake"] = "mcl_candles:candle_cake"
        FULL[f"{mc_c}_candle_cake|lit"] = "mcl_candles:candle_cake_lit"
        for n in (1, 2, 3, 4):
            FULL[f"{mc_c}_candle|{n}"] = f"mcl_candles:candle_{n}"
            FULL[f"{mc_c}_candle|{n}|lit"] = f"mcl_candles:candle_lit_{n}"

def fill_stairs():
    for mc, sub in STAIR_MAP.items():
        if mc in FULL:
            continue
        if mc.endswith("_stairs"):
            base = f"mcl_stairs:stair_{sub}"
            FULL[mc] = base
            add_stair_shapes(mc, base)
        elif mc.endswith("_slab"):
            base = f"mcl_stairs:slab_{sub}"
            FULL[mc] = base
            FULL[mc + "|top"] = base + "_top"
            FULL[mc + "|double"] = base + "_double"

def fill_walls():
    for mc, node in WALL_MAP.items():
        if mc not in FULL:
            FULL[mc] = node

fill_wood()
fill_colors()
fill_stairs()
fill_walls()

# Add top/double variants for direct slab entries.
for mc, node in list(FULL.items()):
    if mc.endswith("_slab") and node.startswith("mcl_stairs:slab_"):
        FULL[mc + "|top"] = node + "_top"
        FULL[mc + "|double"] = node + "_double"

# Correct direct door/trapdoor families not covered by wood families.
def add_door_states(mc, base):
    FULL[mc] = base + "_b_1"
    FULL[mc + "|lower"] = base + "_b_1"
    FULL[mc + "|upper"] = base + "_t_1"
    FULL[mc + "|lower|open"] = base + "_b_2"
    FULL[mc + "|upper|open"] = base + "_t_2"

for mc, base in [
    ("copper_door", "mcl_copper:door"),
    ("exposed_copper_door", "mcl_copper:door_exposed"),
    ("weathered_copper_door", "mcl_copper:door_weathered"),
    ("oxidized_copper_door", "mcl_copper:door_oxidized"),
    ("iron_door", "mcl_doors:iron_door"),
]:
    add_door_states(mc, base)

for mc, base in [
    ("copper_trapdoor", "mcl_copper:trapdoor"),
    ("exposed_copper_trapdoor", "mcl_copper:trapdoor_exposed"),
    ("weathered_copper_trapdoor", "mcl_copper:trapdoor_weathered"),
    ("oxidized_copper_trapdoor", "mcl_copper:trapdoor_oxidized"),
    ("iron_trapdoor", "mcl_doors:iron_trapdoor"),
]:
    FULL[mc] = base
    FULL[mc + "|open"] = base + "_open"

for mc_w, mcl_w in WOOD_ALIAS.items():
    FULL[f"{mc_w}_hanging_sign|attached"] = f"mcl_signs:hanging_sign_attached_{mcl_w}"
    FULL[f"{mc_w}_wall_hanging_sign"] = f"mcl_signs:hanging_sign_wall_{mcl_w}"

# ---------------------------------------------------------------------------
# 5. Validate + report
# ---------------------------------------------------------------------------
missing = sorted((k, v) for k, v in FULL.items() if not node_ok(v))
print(f"total mappings: {len(FULL)}")
print(f"invalid node names: {len(missing)}")
for k, v in missing:
    print(f"  {k} -> {v}")

# Coverage report over the full MC block list
mapped = [b for b in MC_BLOCKS if b in FULL]
unmapped = [b for b in MC_BLOCKS if b not in FULL]
print(f"\nMC blocks total: {len(MC_BLOCKS)}")
print(f"MC blocks mapped: {len(mapped)} ({100*len(mapped)//len(MC_BLOCKS)}%)")
print(f"MC blocks unmapped: {len(unmapped)}")
print("unmapped list:")
for b in unmapped:
    print(f"  {b}")

json.dump(FULL, open(os.path.join(HERE, "full_mapping.json"), "w"), indent=1, sort_keys=True)
print("\nsaved", os.path.join(HERE, "full_mapping.json"))
