# Human annotations from the Kick Check page (tools/annotate)

Human ground truth: use these over stem-derived labels when they disagree.

- `<NN>.json`: kick_add / snare_add = the user's taps (snapped to the stem attack when "snap" was on),
  wrong = stem labels they marked wrong, misfire = detector hits they marked bad, notes = free text.
- Output device while marking (said by the user, 2026-11-18):
  - **01 (DARK ARM): tapped on the K3 Bluetooth speakers (~250 ms late)**, before the page compensated.
    Matched to the stem at a fitted shift of 255-270 ms. Backup of those taps: `01_taps_backup_late.json`.
    Its 26 `wrong` marks refer to the old v1 labels (bench.drum_hits), which are gone in v2.
  - **Every other track: marked without delay** (not on the K3s).
- Track 01 notes: no kicks before ~0:54 or after ~4:55; "the stems otherwise are pretty solid".
