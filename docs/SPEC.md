# PROMPT: Project / Part Tracking ERP Software Running on a Local Server

> Give this file to Claude Code (or another coding agent). The `ornek_veriler/`, `referans_ciktilar/` and `referans_kod/` folders in the same directory are part of the prompt; read all of them first.

---

## 0. What you are asked to do

Develop **a web-based ERP / project and part tracking software that is easy to install on a local server (offline network)** for the mechanical design team of a defense industry company.

Today this work is done by hand:
1. The assembly BOM is exported from SolidWorks as `.csv`.
2. A "Tracking List" Excel file is produced from the BOM: parts list, status tracking, fastener summary, summary sheet with charts.
3. As new BOMs arrive, the list is updated; earlier statuses (produced, ordered, etc.) are kept.
4. The technical drawings of the parts (PDF/DWG/SLDDRW) are kept in separate folders.

The software must handle this whole flow in a single web interface. We must still be able to get Excel output.

The Python code in `referans_kod/` is a working prototype of these rules. The Excel files in `referans_ciktilar/` are the target output format. Derive the business rules from these and from the sections below. You do not have to copy the code, but the behavior must be the same.

---

## 1. Operating environment and constraints (strict)

- **Offline local network.** While running, the app must not connect to any external resource (CDN, Google Fonts, external API, telemetry). All JS/CSS/fonts must be bundled.
- **One-command installation:** `docker compose up -d`. It must run on a Linux server and on Windows (Docker Desktop). The README must describe installation, updating, backup and restore step by step.
- **Offline installation:** Prepare a script and a README section for building the images on a machine with internet (`docker save`) and moving them to the offline server.
- **The interface language is Turkish.** Turkish characters (ı, İ, ş, ğ, ü, ö, ç) must work correctly everywhere, including CSV reading, search, sorting, file names and Excel output.
- Data and uploaded files must persist in Docker volumes. A daily automatic backup must be taken (database dump + files, the last N days are kept).

## 2. Technology stack

Use this unless you have a reason not to; if you want to change it, ask first and give your reason.

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic (migrations), Pydantic.
- **Database:** PostgreSQL 16.
- **Excel:** openpyxl (reading and writing, including data validation, conditional formatting and charts).
- **Frontend:** React + TypeScript + Vite. TanStack Table for tables (virtual scrolling, column filters, multi-select, inline editing). Recharts for charts. Everything bundled, no CDN.
- **File storage:** Local file system (volume). File metadata is kept in the database.
- **Reverse proxy:** nginx (frontend static files + `/api` forwarding). Limits for large file uploads (≥ 2 GB bulk upload) must be set.
- **Authentication:** User name + password, JWT or session cookie. An admin user is created on first installation.

## 3. Core concepts and data model

Use the model below as the basis; extend it if needed.

- **Project:** for example "T-35". Main assembly number (T01_0000_0000), description.
- **BOM Version:** Every CSV uploaded to a project is a new version. Stored: upload date, uploader, file name, note. Versions are never deleted; the history can be viewed.
- **Part (master):** A unique record per part number. Across projects and versions, the same part number is the same record. Status information belongs to it.
- **BOM Row:** Each row in a version. Stored: level ("1.3.2.4"), parent assembly, main group (level-1 assembly), quantity, total quantity, material, weight, revision, procurement type, coating, row type (Part / Assembly / Fastener / Inside a purchased assembly).
- **Tracking Record (per project + part):** procurement type (the user can change it; it overrides the BOM value), progress, notes, external status note (T-35 note), manufacturer/company.
- **Shortage / Extra Quantity:** An extra requirement row linked to a part (quantity, reason, its own progress). Example: "T01_2200_0026 - should be 8, there are 4 - 4 missing".
- **Part Alias:** User mappings such as "T01_2000_0002-P = T01_2000_0002". When a part arrives with a new number, it inherits the old status.
- **Fastener Item:** Normalized standard + size (e.g. "DIN 912 / ISO 4762 - M12x55"). Total quantity and order status.
- **Technical Drawing File:** file name, extension, size, hash, upload date, uploader, matched part, revision (if it can be read from the file name), version history.
- **Change Log (audit log):** who, when, on which record, which field, old value → new value.
- **Users and roles:** Admin, Designer (uploads BOMs and drawings), Planning/Purchasing (updates status), Viewer (read only).

## 4. BOM CSV import rules

The sample files are in the `ornek_veriler/` folder.

### 4.1 File format
- Separator `;`, encoding UTF-8 with BOM (`utf-8-sig`). Headers: `Level;Dosya Adı;Reference Count;Malzeme;Ağırlık;Revizyon;TeminSekli;Kaplama Bilgisi`.
- `Level` gives the hierarchy: `1`, `1.1`, `1.1.2`, … Indentation spaces at the start of file names are removed.
- Part number = the file name without its extension (`.SLDPRT`, `.SLDASM`, `.sldprt`, case-insensitive). `.SLDASM` = assembly.
- "Material <not specified>" and "Malzeme <belirli değil>" → empty material ("Unspecified").
- Weight uses a decimal point; assume grams.

### 4.2 Quantity calculation
- **Total Quantity = row quantity × the product of the quantities of all parent assemblies.** Example: T01_0050_0000 (2) → T01_0051_0000 (2) → T01_0051_0002 (2) = 8.
- The same part can appear in more than one assembly (e.g. T01_0600_0001 in eight different assemblies). The rows are shown separately. The total requirement must also be computable (summed per part).

### 4.3 Purchased assemblies
- An **assembly** with the procurement type "Purchased" is bought as a single item. The parts under it are not tracked separately: they are shown in grey as "Inside a purchased assembly" and are not counted.
- The user must be able to mark an assembly later as a "single purchased item". Example: the 30 parts with supplier codes (26.2108.xx, 2000xx.R00) in the TSDacikboy subassembly; their procurement type in the BOM is empty, but they are bought as one item. This mark is stored in the part record and stays valid for later BOM uploads.

### 4.4 Recognizing and normalizing fasteners
Extract the type, standard, diameter and length from the file name. All patterns are in the `fastener()` function in `referans_kod/parse.py`. In short:

| Sample file name | Type | Standard (normalized) | Size |
|---|---|---|---|
| `DIN 912 M10 x 65 --- 32N` | Bolt | DIN 912 / ISO 4762 | M10x65 |
| `ISO 4762 M12 x 20 - 20N` | Bolt | DIN 912 / ISO 4762 (same part, merge) | M12x20 |
| `DIN 7991 - M3 x 10 --- 6.8N` | Bolt (countersunk head) | DIN 7991 | M3x10 |
| `Hexagon Nut ISO 4032 - M16 - W - N` | Nut | ISO 4032 / ISO 4034 / DIN 6915 | M16 |
| `DIN EN ISO 8733-8x30-St` | Pin (cylindrical, internal thread) | DIN EN ISO 8733 | Ø8x30 |
| `DIN EN ISO 8750-5x45-St` | Pin (coiled spring) | DIN EN ISO 8750 | Ø5x45 |
| `DIN EN 28734 - 3 x 8 - A - St` | Pin (hardened cylindrical) | DIN EN 28734 (ISO 8734) | Ø3x8 |
| `DIN 94-6.3x28-C-St` | Pin (split pin) | DIN 94 | 6.3x28 |
| `Washer DIN 125 - A 10.5` / `Washer ISO 7089 - 10` | Washer (flat) | DIN 125-A / ISO 7089 (same part, merge) | Ø10.5 (M10) |
| `Washer DIN 125 - B 17` | Washer (chamfered) | DIN 125-B | Ø17 (M16) |
| `Spring washer DIN 128 - A10` | Washer (spring) | DIN 128 | A10 (M10) |
| `Parallel key A12 x 8 x 32 DIN 6885` | Key | DIN 6885 | A12x8x32 |
| `Circlip DIN 471 - 30 x 1.5` | Circlip | DIN 471 | 30x1.5 |

- Unrecognized non-standard names are taken as parts and flagged with a "non-standard name" warning (e.g. `gps anteni`, `Kauçuk1`, `montaj Ø1400`, `35MM DIN RAIL-12`).
- The patterns must be kept in a settings file or in the database; adding a new pattern must not require a code change (a regex + mapping can be defined from the admin screen).

### 4.5 When a new BOM version is uploaded
- Compare it with the previous version **by part number**. **Ignore** weight differences; only part numbers matter. Revision, material, procurement and quantity differences are shown as information.
- The result screen ("BOM Comparison") is shown before approval:
  - Newly added parts,
  - Removed parts (a red warning if the part has progress: "A part in Produced status was removed from the BOM"),
  - Parts whose revision changed (if the part is "Produced"/"Completed", a warning: "may have been produced with the old revision"),
  - Quantity changes,
  - Fastener item/quantity changes (a warning if the total quantity drops sharply).
- **Possible match suggestion:** If a removed number and a new number differ only by a suffix (`-P`, `-1`, etc.), ask the user "is this the same part?". If the answer is yes, create an alias and carry the status over. If no, it stays a separate part.
- After approval:
  - The tracking data of existing parts (procurement change, progress, notes, shortage rows) is **kept**.
  - New parts are added with the default status and get a "New" label (the label stays until the user removes it or until the next version).
  - Removed parts leave the list but are archived in the database; they can be seen in the earlier version.
- Undo: the last BOM upload must be reversible.

## 5. Status logic (important)

The user does not pick the status directly. They pick **"Progress"**; **"Status"** is derived automatically from the procurement type. This way, when the procurement type changes, the status changes automatically too, and charts and counts update at once.

Progress options: **Waiting / In progress / Completed**

| Progress | Procurement = Manufacturing | Procurement = Purchased | Assembly (not purchased) |
|---|---|---|---|
| Waiting | Not produced | Not ordered | Not assembled |
| In progress | Not produced | Ordered | Not assembled |
| Completed | Produced | Order delivered | Assembled |

- If the procurement type is "Unspecified", Status = "No procurement selected" (red).
- Colors: Not produced `#F8CBAD`, Produced `#BDD7EE`, Not ordered `#FFC7CE`, Ordered `#FFEB9C`, Order delivered `#C6EFCE`, Not assembled `#E7E6E6`, Assembled `#D9C3E9`. Shortage rows purple (`#E4DFEC`), new parts green (`#D9EAD3`).
- Extra fields: Manufacturer/Company (e.g. ROBOLEGO, İHMA, HAS-MAK; the list is managed by admin), material status (From stock / Material to be requested / Ordered / Reordered / Material arrived), free note.
- Every status change is written to the audit log. A timeline is shown in the part details.
- Bulk update: multi-select in the table → "Set progress" / "Set procurement type".

## 6. External status list import (T-35 Current Status type)

Example: `ornek_veriler/T-35_Guncel_Durumu.xlsx`. Columns: No, Dosya Adı, Reference Count, Malzeme, Ağırlık, Revizyon, Durum (free text, multi-line).

- Map the free text to progress. The rules are configurable; defaults:
  - "TAMAMLANDI", "İHMA HAZIR" → Completed
  - "ÜRETİMDE", "İMALATTA" → In progress
  - Others → Waiting
  - A company name found in the text → Manufacturer
  - The whole text → the "T-35 Note" field (do not write a note if the text is only "ÜRETİM TAMAMLANDI")
  - "SİPARİŞ VERİLMEMİŞ" + "STOK" → material status "From stock"; "TEKRAR MALZEME" → "Reordered"; "DAHA ÖNCE" → "Ordered"; "MALZEME SÖYLENECEK" → "Material to be requested"
- Show a comparison table in the import preview: in the BOM but not in the list, in the list but not in the BOM, revision difference ("DİKKAT" if produced), quantity difference. Apply it when the user approves.
- Cell background colors (red/orange marks) are taken as a "marked red in the external list" note.

## 7. Technical drawing management

- **Bulk upload:** Multiple file selection, drag and drop, folder upload and `.zip` upload. The supported extensions are at least: PDF, DWG, DXF, SLDDRW, SLDPRT, SLDASM, STEP/STP, PNG/JPG.
- **Automatic matching:** The file name (without extension) is the same as the part number. Matching rules:
  - Case-insensitive; leading/trailing spaces and `_`/`-` differences are normalized.
  - If the file name has a revision suffix, parse and store it, as in `T01_2110_0004_RevD.pdf`, `T01_2110_0004-D.pdf`, `T01_2110_0004 (Rev C).pdf`.
  - The mappings in the alias table are used.
  - A part can have more than one file (PDF + DWG + SLDDRW): they are grouped by type.
  - A file uploaded again with the same name becomes a new **version**; old versions are kept and can be downloaded.
- **Unmatched screen:** Files that were not matched automatically are listed. A similar part number is suggested (fuzzy match). The user matches them by hand or deletes them.
- **In the parts list** there is a technical drawing column. Parts that have drawings show icons in this column (PDF/DWG/…), and manufactured parts without a drawing get a "no drawing" warning. There must be a "Manufactured parts without drawings" filter.
- **Viewing:** PDFs open in the browser (bundled pdf.js; no external resource). DWG/SLDDRW files are downloaded. If available, a small preview is generated from the first page of the PDF.
- **Revision check:** Warn if the revision on the drawing does not match the revision in the BOM.
- **Bulk download:** Download the drawings of the selected parts or of a main group as `.zip`. For sending to suppliers, there must be an optional "PDF only" or "PDF + DWG" choice.

## 8. Screens

1. **Sign-in**
2. **Projects:** list, new project.
3. **Project Summary (dashboard):**
   - KPI cards: manufacturing progress %, produced/total, purchased items delivered/total, fastener count and delivered, shortage quantity, number of manufactured parts without drawings.
   - Pie charts: manufacturing status, purchase order status, fastener types, fastener order status.
   - Main group table and horizontal stacked bar chart (produced/not produced per main group, progress bar).
   - Everything is calculated from live data.
4. **Parts List:**
   - Tree view (assembly hierarchy, collapsible) and flat view ("parts only": assemblies hidden; purchased assemblies as a single row).
   - Columns: Level, Part No, Type, Main Group, Parent Assembly, Qty, Total Qty, Material, Weight, Procurement Type, Coating, Rev, Progress, Status, Manufacturer, T-35 Note, Note, Technical Drawing.
   - A filter on every column (multi-select + text search). The number of filtered rows and the total quantity appear at the top.
   - Inline editing, bulk editing with multi-select.
   - Part detail panel: details, technical drawings, status history, assemblies where it is used, shortage rows.
5. **Fasteners:**
   - Detail tab: rows per assembly, quantity × multiplier.
   - Summary tab: total per item, main groups where it is used, order status, spare % and order quantity calculation (rounded up), supplier, unit price.
6. **BOM Versions:** upload, comparison screen (see 4.5), version history.
7. **Technical Drawings:** bulk upload, unmatched files, all files.
8. **Control List:** Problems the system finds automatically and issues opened by users (Open/Resolved):
   - Parts with an empty material or procurement type,
   - Non-standard names,
   - The same number used as both a part and an assembly (example `T01_0004_0014`),
   - The same part in the same assembly both inside a subassembly and directly (possible double count, example `T01_0051_0012`),
   - Inconsistent material names (`5083-111` / `5083-H11`),
   - Revision warnings,
   - Manufactured parts without drawings.
9. **Administration:** users and roles, company list, fastener patterns, status mapping rules, backup status, audit log viewer.

## 9. Excel outputs

Every table can be exported. Grids export all filtered rows, plain tables export what the page shows, and administrators can export all data except users, settings and chat messages, one sheet per table. Paged plain tables export the page on screen.

The two files in `referans_ciktilar/` are the target format. Produce the same structure with openpyxl:

1. **Tracking List (full):** Summary, Parts List (assemblies included, indented), Fasteners, Fastener Summary.
2. **Part Tracking (simple):** Summary + Parts List; assemblies removed, purchased assemblies as a single row.

What the Excel files must have:
- Arial font, a dark navy (`#1F3864`) header row, thin grey borders, gridlines off, the header row frozen, autofilter on, landscape page and fit to page set.
- The **Progress** column has a drop-down list (yellow background). The **Status** column is a formula (`=IF(...)`, the table in section 5). If the procurement type is changed in Excel, the status changes there automatically too.
- A drop-down list in the Procurement Type column.
- Status colors through conditional formatting.
- "Filtered rows" and "filtered total quantity" counters at the top using `SUBTOTAL`.
- On the summary sheet, KPI cards calculated with formulas, pie charts and a main group bar chart. They must update when the user makes changes in Excel.
- Extra outputs: a fastener order form (item, standard, size, requirement, spare %, order quantity, unit, unit price, amount), an "export visible" option for the filtered table.
- **Import back from Excel:** The user must be able to change Progress/Procurement/Note in an exported Excel file and upload it again. The system matches rows by part number + parent assembly, previews the differences and applies them when approved.

### 9.1 Comparing any workbook

`POST /api/excel/{project}/compare` (`services/excel_compare.py`) reads `.xlsx`, `.xlsm`, `.xls` and `.csv` files.
Nothing is saved at this step; the existing apply endpoint saves the rows the user selects.

- The app's own tracking export is recognised and goes through the normal import preview.
- In any other file, the header row is the row with the most known titles. The part column is the column that
  matches the most project parts. Other columns are found by title, then temin and status columns by their values.
- Parts match by part number, then alias, then a loose key without separators and case. Fasteners, parts inside
  purchased assemblies and the root row are skipped.
- Blank cells keep the stored value. For purchased parts, the order column is read before the status column.
- The response lists changes, part numbers not in the project, invalid values, project parts not in the file, the
  detected layout of each sheet, status words that could not be read and temin names that are not defined.
- The client can send back a `config` with corrected columns and value meanings. The file is then read again.
- Only an administrator can add a new temin type, and this happens at apply time.

## 10. Quality and acceptance criteria

- Write unit tests for the backend with pytest: CSV parsing, quantity multiplication, fastener patterns, BOM comparison, status derivation, T-35 mapping, drawing file name matching.
- Expected results for `ornek_veriler/BOM_T01_0000_0000_2026-11-02.csv` (with TSDacikboy marked as a "single purchased item"):
  - 450 BOM rows, of which 388 are part/assembly rows and 62 are fastener rows.
  - The fasteners reduce to 43 unique items, with a total quantity of **1006**.
  - The number of rows left inside purchased assemblies (not tracked) is 60.
- Comparing `BOM_T01_0000_0000_2026-10-31.csv` → `2026-11-02.csv` must find:
  - The T01_3000 group was removed completely; T01_0001_0000 and its parts, T01_0000_0005, T01_0000_0016 and T01_2000_0007 were removed.
  - Newly added: the T01_6000_0000 group, the T01_6000_0000-P group, T01_2000_0002-P.
  - Fastener total 1642 → 1006.
- When `BOM_T01_0004_0000_v1/v2/v3.csv` are uploaded in order:
  - v1 → v2: Part1-1 is added, the material of T01_0004_0028/0029 becomes EPDM, 16 parts get Rev A.
  - v2 → v3: Part1-1 is removed, T01_0004_0033 is added, T01_0004_0001 becomes Rev B, DIN 912 M6x12 (6 pcs) and a Ø5x18 pin (2 pcs) are added.
- When the Excel output is recalculated in LibreOffice, there must be no formula errors (#REF!, #NAME?, etc.).
- The parts list must stay smooth with a BOM of 2000+ rows (virtual scrolling).

## 11. Way of working

1. First read this file and the attachments. Ask about anything unclear, point by point, **before writing any code**.
2. Draw up a short architecture plan and database schema and get approval.
3. Develop in stages; at the end of each stage there must be a working version that starts with `docker compose up`:
   - **Stage 1:** Infrastructure (Docker, DB, auth, project), BOM import, Parts List screen, Progress → Status logic.
   - **Stage 2:** BOM version comparison and status carry-over, aliases, shortage rows, dashboard.
   - **Stage 3:** Technical drawing upload, automatic matching and viewing.
   - **Stage 4:** Excel export/import (exactly the same format as the reference outputs), import of T-35 type external lists.
   - **Stage 5:** Fastener order module, control list, administration screens, audit log, backup.
   - **Later stages (leave room for them in the design for now):** purchase orders and supplier cards, stock/warehouse, work orders, cost tracking.
4. Update the README at every stage. Add a `seed` command that creates a demo database from the sample data.
5. Write clean, layered, commented code. Business rules (patterns, mapping tables) must be configurable, not hard-coded.

## 12. Attachments

- `ornek_veriler/`
  - `BOM_T01_0000_0000_2026-10-31.csv`, `BOM_T01_0000_0000_2026-11-02.csv`: two BOM versions of the main assembly
  - `BOM_T01_0004_0000_v1.csv`, `_v2.csv`, `_v3.csv`: three versions of a subassembly (for the comparison test)
  - `T-35_Guncel_Durumu.xlsx`: sample external status list
- `referans_ciktilar/`
  - `T01_0000_0000_Takip_Listesi.xlsx`: full tracking list (target Excel format)
  - `T01_0000_0000_Parca_Takip.xlsx`: simple part tracking (target Excel format)
- `referans_kod/`
  - `parse.py`: BOM parsing, quantity multiplication, purchased assembly detection, fastener patterns, T-35 reading
  - `build_takip_excel.py`: the prototype that produces the Excel outputs (status carry-over, Progress → Status formula, summary and charts). File paths are hard-coded for the prototype; use it only as a reference for the logic.
