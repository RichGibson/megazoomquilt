# passport_drive_two/gigapan — New Panoramas To Process

Found in `/Volumes/bigeneration/passport_drive_two/gigapan`.
Almost all are NEW (not in gigapan_list.json, not imported).
Most have a small .jpg preview + a large .psd/.psb stitched file + a .pano project file.

## Decision needed
For each item: tile the .psd/.psb, or re-stitch from source images via the .pano file, or skip.

---

## Vienna

| File | Size | Has .pano |
|---|---|---|
| mariahilferstrasse_oct_21.jpg | 6.5MB jpg only | no |
| mt_night_0004.jpg / mt_night_try2_0000.psd | 158MB jpg / 1.58GB psd | yes |
| mt_platz_lights_0000.psd | 1.15GB psd | yes |
| mt_platz_stonework_0000/0001.jpg | small jpgs | yes |
| rathaus_rear_oct_2014_0000.jpg | 5.5MB jpg | yes |
| schwedenplatz_noodles_0000.psd | 668MB psd | no |
| thalia_apotheke_0000.psb | 1.45GB psb | yes |
| top_kino_0000.jpg | 4.6MB jpg | yes |
| tram_2_0000.psd | 1.81GB psd | no |
| mq_winter_opening_0001.jpg | 241MB jpg | no |

## Rome / Vatican

| File | Size | Has .pano |
|---|---|---|
| coloseum_bowl_0000.jpg | 3.8MB jpg | yes |
| coloseum_detail_0000.psd | 1.42GB psd | yes |
| coloseum_straps2_0002.jpg | 94MB jpg | yes |
| forum_0000.psd | 117MB psd (in gp_list) | yes |
| palatine_mosaic_0000/0001.jpg | small jpgs | no |
| rome_from_colosso_0000.psb | 1.83GB psb | yes |
| sarcophagus_0002.psd | 1.18GB psd | yes |
| st_peters_night_b_0003.jpg | 95MB jpg | no |
| vatican_gold_0000/0001.jpg | small jpgs | no |

## California Coast

| File | Size | Has .pano |
|---|---|---|
| jughandle_bridge_0000.psd | 812MB psd | no |
| mendocino_town_larger_0000.psb | 1.57GB psb | no |
| mendocino_town_smaller_0000.psd | 1.33GB psd | no |
| noyo_harbour_dolphin_isle_crop.psd | 1.12GB psd | no |
| worker_gypsy_wagon_0001.tif | 285MB tif | yes |

## MAK Museum (Vienna)

| File | Size | Has .pano |
|---|---|---|
| mak_cases_0001.psb | 1.69GB psb | no |
| mak_ceramic_sculpture_0000.psd | 950MB psd | no |
| mak_jewelry_case_0000.psd | 639MB psd | no |
| mak_stacked_glassware_one_0000.psd | 456MB psd | no |

## Sculptures / Art (likely Vienna)

| File | Size | Has .pano |
|---|---|---|
| bruder_schwadron_0000.jpg | 0.4MB jpg | yes |
| centaur_death_a.psd / centaur_death_2_0000.psd | 676MB / 1.15GB psd | yes |
| curious_bull.jpg | 2.1MB jpg | yes |
| equestrian_0000.jpg / equestrian_2_0000.psd | 6.7MB jpg (in gp_list) / 857MB psd | yes |
| esel2_0000.psd | 1.76GB psd | yes |
| esel3_0000.psb | 2.81GB psb | yes |
| isis1_0000.psb / isis1_0000.psd | 2.06GB psb / 2.84GB psd | yes |
| isis2_0000.psd | 706MB psd | no |
| nail_statue_0000.jpg | 2MB jpg | no |
| shards_1_0000.psb / shards_1_0000.psd | 1.36GB psb / 506MB psd | yes |
| shards_2_side_0000-0004.jpg | tiny jpgs | no |
| stone_sculpture.jpg | 6.3MB jpg (in gp_list) | yes |
| temple_one_0000.psd | 550MB psd | no |

## Portraits

| File | Size | Has .pano |
|---|---|---|
| portrait_martin_bookweit2_0000.jpg | 50MB jpg | yes |
| portrait_martin_bookweit4_0000.psd | 898MB psd | yes |
| portrait_spencer_1.psd | 771MB psd | yes |
| lukas_0000.jpg | 30MB jpg | yes |
| richhand_0000.psd | 1.22GB psd | no |
| mom_don_bookshelf.psd | 1.66GB psd | no |
| football_jacket_0000.psd / football_jacket_0001.jpg | 607MB psd / 120MB jpg | yes |

## Other

| File | Size | Has .pano |
|---|---|---|
| wiesnfest_0000.jpg | 50MB jpg (in gp_list) | yes |

---

## Notes
- Files marked "in gp_list" were uploaded to gigapan.com but not yet imported locally
- Where both .psd and .psb exist for the same subject, .psb is likely the higher-res version
- Where only a .jpg exists (no .psd), that jpg may be the final stitched output — tile directly
- Large .psb files require `vips` for conversion (already installed)
- `forum_0000.psd` is in gigapan_list — run reconcile after importing to get metadata
