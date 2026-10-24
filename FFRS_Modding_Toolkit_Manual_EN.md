# FFRS Modding Toolkit — User Manual

# Before you start

1. Install Python and the required packages. Python 3.14 is recommended; other versions are untested. See `/Python_Environment_EN.md` (English: `/Python_Environment_EN.md`).

2. Download the external tools and put them in `/tools` or the matching subfolder. See `/tools/ExternalTools_EN.md` (English: `/tools/ExternalTools_EN.md`).

3. `ffr-dt.exe` must be built from source; see `/tools/ffr-dt/BUILD_README_EN.md` (English: `/tools/ffr-dt/BUILD_README_EN.md`).

4. Audio key: not bundled in the public build. Run `python/FFRS_AudioKeyTool.py`, select the game root, and it will recover the key into `tools/criwarekey.txt`. You can also paste the key into that file manually (template: `tools/criwarekey.example.txt`). The key is only needed for audio decode/encode; video, skill, and sprite tools work without it.

# Usage

## Sprite Analyzer & Converter

1. **Character assets:** put the extracted sprite sheet and its `uasset/uexp` into the import folder under `/char`. (The sprite sheet can be extracted with FModel; `uasset/uexp` can be extracted with `retoc -legacy`.) Click **Scan** to list editable characters, then pick the character to export / preview / restore from the dropdown.

2. **Parse / refresh preview:** parses the selected character's animations and parts, and shows the result in the animation preview window. Switch character and click again to refresh the preview.

3. **Export current animation PSD:** exports sprite parts as a layered PSD. Reused parts are not exported twice, and parts used by the first frame of the idle animation are fully exported first.

   - **Standard** = preview appearance
   - **safe 1px** = preview appearance plus a 1-pixel black safety border, so edited parts stay inside the frame and restoring the sprite sheet is guaranteed to be safe. (Coordinates are anchored at the top-left, so extending parts to the bottom-right should also be fine — feel free to experiment.)
   - **Numbered** = preview appearance plus part numbers; the number equals the cell number in the PSD layer name. (All cell numbers shown in the tool are consistent, so you can locate which part to edit.)

4. **Export current frame PSD:** exports the frame currently shown in the preview as a layered PSD.

5. **Export current character assets as PSD:** essentially exports PSD layers as part PNGs. An early feature; not recommended.

6. **Export parts:** exports part PNGs without going through a PSD. An early feature; not recommended.

7. **Check PSD layers:** verifies that the edited PSD layers are valid (naming, duplicates, etc.). A summary appears in the log and a report is written to the output folder.

8. **Compare PSD layers:** if the check reports a problem but you cannot find it, compare the edited PSD with the exported PSD. Log/report behave as above.

9. **Search part animation references:** enter a part number to see which animations use that part. Useful for fine-tuning or unbinding animations and parts later.

10. **Remove part animation references:** the original and the replacement character are designed differently, so you can unbind a part from an animation (i.e. the part is not shown while that animation plays). You can unbind the whole animation or only a frame range (e.g. hidden on frames 0–10, visible from frame 11 on).

    **Note:** only unbinding is implemented — there is no re-binding. Always keep backups!

11. **Edit animation frames:** because the character changes, some frames may look odd and must be adjusted so the sprite sheet still restores safely inside the frame. Drag the slider in the preview to the keyframe you want, click **Edit animation frame**, then in the new window click the part to adjust, drag it with the left mouse button or move it with A/S/D/W, and click **Record current changes** (stored in memory only, not written to `uexp`). Close the window, pick another keyframe, keep editing; finally click **Save animation frames** to write all changes at once.

    **Note:** the saved `uexp` goes to the output folder. To edit again you must replace the `uexp` in the import folder — so keep backups! (The tool backs up the current `uexp` in the import folder automatically, but repeated replace/edit cycles still need manual backups.)

    **Note 2:** if the output folder already contains the `uexp` for the current character, saving is blocked for safety — that is a backup reminder.

12. **Original sprite sheet:** scans the import folder; pick the original sprite sheet of the current character from the dropdown. This is the first step of restoring.

13. **Modified PSD:** scans the import folder; pick the modified sprite sheet of the current character from the dropdown. (PSD/TIFF and similar formats are theoretically supported, but the tool exports PSD by default, so PSD is recommended for restoring.)

14. **PSD export textures:** default is `all` (`_tex` / `_mreo` / `_normal`).

15. **Restore Sprite from PSD:** when all edits are done and the PSD check/compare passes, click this to turn the layered PSD back into a single sprite sheet.

    **Note:** after baking the sprite sheet in UE 5.6, remember to include the modified `uexp/uasset` (the `uasset` itself is not modified, but it is needed for packaging) and package with `retoc -zen`.

## Outline Generator

Simulates FFRS's outline textures. Very simple to use: put the sprite sheet restored in the previous step back into the import folder, scan and select it, then generate `_mreo`.

The normal map workflow is described inside the tool and requires NVIDIA Texture Tools Exporter. In theory any tool that can convert an alpha channel into a normal map works. **Correct Normal Outline** is optional; importing the generated normal map lets you adjust by a few pixels — the visual difference is subtle.

## Final Blow Animation Replacer

1. **Parse:** parses the assets in the import folder and the original USM videos (export USM with FModel → Export Raw); preview below.

2. Choose the original video / replacement video and audio, then click **Build MOD** to replace the Final Blow animation.

   **Note:** video length cannot be changed (not even via UE4SS hooks), so the replacement video/audio must match the original length. If shorter, it loops; if longer, it is cut off midway. Replacement videos support the Alpha channel (transparency requires the original movie to have alpha).

3. **Volume:** the game's BGM can partially mask replaced audio, so you can raise the volume if needed (default is aligned with the original).

   **Note:** the vision biography animations in the祠堂 (Legend hall) can also be replaced with this tool.

   **Note 2:** the original USM contains no audio at all. This tool looks up the corresponding audio asset in the game folder and packages the replacement itself, so audio inside the imported video is never read — to change sound you must provide a separate audio file.

   **Note 3:** vision hall dialogue and videos are not one-to-one; to replace them together, use the next tool.

## Story Script & Audio Replacer

1. **Parse:** parses all text related to the character.

   **Note:** this tool only reads texts in the game's Localization. FFRS skill texts are not listed here; modify them in the Skill tool instead.

2. **Export / import dialogue:** exports story dialogue as an Excel sheet; fill it in and use **Import dialogue** to import in bulk. You can also fill in replacement audio paths in one go (e.g. `C:\xxxx\yyy\zzz\replacement_audio\.wav`).

3. After parsing, edit the languages you need on the right; Simplified Chinese, Traditional Chinese, Japanese and English are supported. After editing a single entry press **Ctrl+Enter** to stage it. Search and bulk replace are available below (very handy for character names or terms); when done click **Stage all**.

4. **Subtitles** in the left list correspond to the subtitles shown during Final Blow animations. Select a subtitle, edit the text and enter the subtitle start/end time in the timeline fields; press **Ctrl+Enter** to stage.

   **Note:** movie start defaults to 2.0 and should not be changed casually. If all Final Blow animations share the same subtitle timing logic, they most likely all have this 2-second lead-in; only consider changing it when you consistently see a timing offset.

5. When all texts are done, click **Build MOD**.

## Skill Modification Tool

1. **Load:** loads a character's skill tables. Hero / vision / esper skill tables can all be modified.

2. After loading, double-click the skill you want to modify to open the edit view.

3. Editing is roughly divided into: **direct edit** (double-click into the edit view and change the current skill), **replace skill** (replace A with B directly), and **new skill** (choosing a new ID during replacement starts the new-skill flow; currently only new skills can have their name/description changed). See the built-in help in the tool for details — it is quite involved: besides simple replacement and numbers, you can edit bundled buffs/debuffs and freely combine a skill's attack animation and effects. (I forget the details myself, which is why the help is built in.)

4. Changes are staged automatically. You can modify multiple skills and build one MOD at once. (The FFRS skill table is written in a tricky way; it is best to finish all skill changes before building, otherwise... use the next tool.)

   **Note:** new IDs start from the first free slot in the game's skill table and increase from there. Besides avoiding replacing original skills, this is also used for MOD-merge identification. Let the tool generate IDs; manual IDs are not guaranteed to work (probably fine, but...).

## Mod Merge Tool

It automatically detects the MODs in the output folder. Usually you only need to remember:

1. Merge **all non-skill MODs** with the normal **Merge** button.

2. Merge **all skill MODs** with **Smart merge**: scan new skills first, then merge.

   **Note:** merging non-skill MODs together with skill MODs is not recommended. First, a skill MOD's modified skill name/description exists in only one language (an FFRS limitation with no workaround yet; multiple languages require multiple edits). Second, the skill table has pitfalls that make a `retoc -zen` MOD structurally different — although the tool can now rebuild and merge correctly in theory, failures have still been observed, so forcing a merge only adds analysis work. (Without new skills it is usually fine; with new skills it is easy to get into trouble.)

3. Same skill-table pitfall: multiple skill MODs cannot coexist (they share the same table header, so when the game loads them they override each other and only the last one takes effect). Therefore, to use skill MODs made by different people, they must be merged. If several MODs all create new skills, you must fill in `(new skill ID : animation source ID : effect source ID)` during Smart merge. (For multiple skill MODs made on this machine no manual input is needed; when sharing with others, share the new skill IDs scanned in Smart merge as well.)

# Final words

The big blue fat fish is still fairly reliable. Have fun!
