Windows desktop app: download and run `LabERP-Setup-x.y.z.exe`.
Android app: download and install `LabERP-x.y.z.apk` on the phone (Android 8.0 and later). This file works on every phone; the `-arm64-v8a`, `-armeabi-v7a`, `-x86_64` and `-x86` files are processor-specific builds.

## What's new in 1.9.0

- **Assembly sheets.** A new project page plans the day's assembly work from the approved BOM. Pick assemblies, set the quantities and drag them into the reservation order, then publish the plan.
- **Printable documents.** One black-and-white PDF holds the daily plan, the pick list and a sheet per assembly, with drawing pages or a QR drawing list. The same plan exports to an Excel workbook with live formulas.
- **Field entry.** Mark parts on screen with the keyboard, or upload the filled Excel back. You see every change and error first, and apply only what you select. Sheet photos can be stored beside the field screen, but they are not read automatically.
- **Part quantities.** Parts now have ready quantities, and scarce parts are reserved in plan order. Extra quantities stay separate and never hold up an assembly.
- **Readiness.** The dashboard shows the assemblies that are ready and the parts holding up the most assemblies. A notification is sent when an assembly becomes ready.
- **Consistency warnings.** Seven checks compare the plan, the pick list, the sheets and the extra quantities. Every change is kept in the plan's history.

## What's new in 1.8.0

- **Project pictures.** A project can have a picture. Add it in the project form; it appears on the project card in the Projects screen.
- **Fix issues from the Control list.** Issues that need a value now have a **Fix** button: empty material, material mismatch, empty procurement type, missing drawing and revision warnings. Select several rows to give them one value. The value goes into the data, so the issue disappears by itself. Issues about the design structure lead to the product tree.
- **Excel matching in the Product tree.** **Match with Excel** compares any Excel or CSV file with the tree and shows new rows, changed fields and parts missing from the file before anything changes. Level or parent assembly columns place new rows in the right spot. **Start from Excel** builds an empty tree from a file, and **Export to Excel** saves the tree.
- **Export everywhere.** Pages with plain tables have an **Export to Excel** button in the header, with one sheet per table. Projects has its own button, and administrators can export all data from Administration > Backups, one sheet per table. Users, settings and chat messages are not included.
- **Saved table layouts.** Column layouts and views of the Control, Drawings, Stock, Fasteners and BOM lists are now kept on the server. Before, they were lost at the next sign-in.
- **Drawing thumbnails.** Thumbnails no longer stay blank when many PDFs load at once. Rendering several PDFs side by side could crash the server process, so they now render one at a time, and a failed thumbnail is tried again.
- **Connecting to a server.** An address without a port now also tries port 8000, on Windows and Android. Addresses on the local network no longer go through the system proxy. When a connection fails, the Windows app says more about the reason, and the server address card warns about a Public network profile or a missing firewall rule.

## What's new in 1.7.0

- **Compare any Excel with the part list.** In the Parts list, **Import > Compare with Excel** reads any `.xlsx`, `.xlsm`, `.xls` or `.csv` file. It finds the part number, status, order status and procurement columns by itself and shows what would change. Nothing is saved until you click Apply.
- **Column and value corrections.** If a column was guessed wrong, change it under **Column mapping**. Status words the system cannot read are shown so you can say what they mean.
- **Parts missing from the file.** A new tab lists the parts that are in the project but not in the file. Part numbers that are in the file but not in the project are listed too.
- **New procurement types.** Laser Cutting, Bending, Welding, Machining, Assembly, Painting and Heat Treatment are built in and are added to lists saved earlier. An administrator can also add a new type straight from the Excel comparison.
- **Server address on screen.** System Settings and My profile show the address that other computers and phones must enter, with a Copy button.

## What's new in 1.6.0

- **Four languages.** The interface now runs in Turkish, English, Spanish and German. Pick the language in the header or on the sign-in page; dates and numbers follow it. Server messages, notifications and the first-run screens are translated too. The Excel tracking workbook stays Turkish because its formulas and the import depend on that text.
- **Chat.** The message menu button now sits beside the bubble and no longer covers the text. On phones, press and hold a message to open the menu.
- **Open source licence.** The project is now under the GNU General Public License v3.0 or later.
- **English project page.** The README, installation guide (now `INSTALL.md`), specification and screenshots are in English.

## What's new in 1.5.12

- **Chat:** Message editing (48 hours), deleting for me or for everyone, replying, forwarding, reactions, pinning, copying and multi-select were added. The menu opens with a right click or from the arrow on the message.
- **Android notifications:** New messages and alerts arrive even when the app is closed. Tapping the notification opens the relevant screen. The server must be reachable. Delays are possible while the screen is off.
- **Windows notifications:** Notifications arrive when the window is closed or in the background. In client mode too, closing the window leaves the app running in the hidden icons near the clock. To quit completely, right-click the icon and choose "Exit".
- **Fastener stock:** A Stock › Fasteners tab was added. Bolts and nuts from the BOM are listed automatically, and stock and open requirement appear side by side. Receipts, issues, counts and issuing to a project all happen in one window. Minimum stock, shelf and QR label are supported.
- **Unread count:** Deleted messages no longer count as unread.

## What's new in 1.5.11

- **Project deletion:** On a Windows server, "Delete permanently" returned an error and the project was not deleted. The problem was in the backup taken before deletion; it is fixed.
- **Backup (Windows):** On Windows installations that use SQLite the backup never completed, the nightly backup included. It now completes. Restore failed for the same reason and is fixed as well.
- **When the backup fails:** The project is not deleted and the reason is shown on screen. If the administrator chooses to continue with "Delete permanently without backup", this is written to the audit log.
- **Deletion while a backup runs:** If another backup is running, the project is no longer deleted without a backup.
- **Very long text, very large number:** PostgreSQL shows a clear warning instead of "Internal Server Error". Related-record conflicts are also reported clearly.
- **After upgrading:** On a Windows server, take a manual backup from Administration › Backups and check that the file appears in the list.

## What's new in 1.5.10

- **Single rounding rule:** Money 2 decimals, quantity 3, always half up. Screen, Excel and invoice give the same result. The fastener spare quantity also comes out the same as in Excel.
- **Weight:** The product tree and Excel now use the same unit, and the labels state the unit. Values written as kg in old drafts are not converted automatically; check them.
- **Times:** Record timestamps are shown in local time on screen.
- **Phone:** The product tree screen no longer overflows on a narrow screen.
- **Session cookie:** The session now lives in an httpOnly cookie that scripts cannot read, instead of browser memory. When the version is upgraded everyone signs in once.
- **Administrator warnings:** If HTTPS is off and the account request setting is on, the administrator sees a warning on screen. Settings are not changed automatically.
- **Certificate pinning:** The desktop app checks the certificate on every connection. Android does not connect over plain HTTP to a server that has switched to HTTPS.
- **Conflict warning:** Stock, staff, attendance, work order, firm, project, order and invoice forms no longer silently overwrite someone else's record. Bulk edit overwrites on purpose.
- **Public holidays:** Edited from Administration › Public Holidays. Expected attendance and leave days exclude holidays. The administrator enters religious holidays.
- **Closing short in sales:** A sales order can be closed as "Closed incomplete".
- **Automatic credit note:** Returning invoiced goods opens its draft credit note by itself.
- **Document-date exchange rate:** The firm balance can be shown at today's rate or at the rate on the document date, and the exchange difference is written separately.
- **Manual rate on goods receipt:** For a foreign-currency order without a rate, the rate is entered on screen.
- **Camera on plain HTTP:** The barcode screen explains why the live camera did not open and gives the HTTPS path. Scanning from a photo works.
- **Fixed bugs:** File-open crash on Android, the draft credit note of an incompletely closed order not being editable, an error when opening a credit note from a return on PostgreSQL, an invoice being issued twice at the same time, and a black border in label output in the dark theme.

## What's new in 1.5.9

- **Notification centre:** The bell in the top bar shows overdue orders and invoices, low stock and pending approvals. Everyone sees only the subjects they are authorised for.
- **Leave and reports:** An employee requests leave and the administrator approves. Attendance correction requests take the same path.
- **Hours from attendance to work:** The day's attendance is distributed to projects and work orders and flows into cost.
- **Barcode and QR:** Stock, orders and work orders open with the phone camera or a reader. Labels are printed.
- **Order suggestion:** A purchasing suggestion is produced from low stock and open requirements.
- **Work order:** Material consumption, returns and operation steps run from the work order.
- **Foreign currency:** TCMB (Central Bank) rates are fetched and totals are shown in the base currency.
- **Partial shipment and returns:** A sales order is shipped piece by piece and returns are recorded. An invoice is issued from the line.
- **Supplier performance:** On-time and short delivery rates are visible.
- **Project templates:** A project is made into a template and a new project is opened from it.
- **Conflict warning:** In the parts grid a field changed by someone else is no longer silently overwritten; you are asked to choose.
- **Views on the server:** Saved views, column layout and theme follow your account to every device.
- **One-click HTTPS:** Enabled from Administration › HTTPS. Android and the desktop app store the certificate and refuse to connect if it changes.
- **Restore from screen:** Pick a backup or upload a file from Administration › Backups.
- **Security:** A desktop update is not installed without signature verification. The SMTP password is stored encrypted. Reading e-mail, firms and projects is tied to permission. New installations come with account requests off. Chat files, browser security headers and server change approval were tightened.

## What's new in 1.5.8

- **Attendance tracking:** An employee clocks in and out and sees only their own records. An authorised administrator sees everyone, corrects entries and exports to Excel. Weekly overtime is calculated automatically.
- **Important backup fix:** If the database was inside the data folder (Linux servers installed with "Install on my server"), taking a backup could cause later records to be lost. Fixed. Backups no longer grow nested, and restore no longer deletes old backups.
- **Stock:** Simultaneous movements no longer overwrite each other.
- **Numbers:** Orders and invoices opened at the same time no longer fail.
- **Offline:** Without a connection a save is not queued but shows an error immediately. The live indicator reports the correct state.
- **Grid:** When a change arrives from another computer, the selected cell stays on the same row.
- **Invoice:** The same sales order cannot be invoiced twice. A purchase order brings only the part not yet invoiced.
- **Deletion protection:** A firm with invoices or orders, and a stock item with project movements, cannot be deleted.
- **Security:** A staff card is not matched by e-mail (an administrator must link it). The home page feed is filtered by permission. A login lockout no longer locks out someone else. Large requests without login are rejected. The signing key is not in the backup and the backup file is readable only by its owner. CSV formula protection was added. There is a warning for the default admin password. Libraries were updated.

## What's new in 1.5.7

- **Procurement types:** Subcontracted Manufacturing, Standard Part, Supply from Stock and Customer Material were added. Add a new one in System Settings and choose its behaviour, drawing and order suggestion.
- **Spreadsheet-like grid:** Cell and range selection, copy, cut, paste, fill handle, undo, find and replace, context menu and selection total arrived.
- **Columns:** Hide, sort and pin. The layout is remembered.
- **Advanced filter:** Conditional filter per column, AND and OR rule groups, and views saved by name.
- **Bulk change:** Filter and select in list or table mode, then set progress and procurement type for all of them at once.
- **Part name:** A new column. Type it in the grid or paste a part number and name list from Excel. It is also entered in the product tree.
- **Excel file:** The rows and columns on screen download as `.xlsx`.

## What's new in 1.5.6

- **Product tree:** A new screen in the project menu. Build the product assembly by assembly without a CAD list: add sub-assemblies and parts, enter the quantity in the parent assembly, the procurement type, material and weight, and the total quantity is multiplied automatically.
- **Item picker:** Type a number used before to pick it. Its data arrives, and for an assembly its sub-items are added too.
- **Draft and version:** The tree saves itself as a draft. You can also start from an existing BOM version. On submit it becomes a pending BOM version that you compare and approve.
- **Hide:** On the Parts list and Fasteners screens the selected rows are hidden. The row stays in the list, only dimmed; it is dimmed on the Requirements screen too. Quantity, status and requirement calculation do not change.

## What's new in 1.5.5

- **Running in the background:** On the server computer, closing the window no longer stops the system. The app drops to the hidden icons and other devices keep working. To quit completely, right-click the icon and choose "Stop the server and exit".
- **System Settings:** A new tab in Administration. Application name, logo, company details, currency, VAT, payment term, payment methods, document number prefixes, default unit, password and login rules, session timeout, upload limit, backup time and enabled modules are changed here.
- **Suitable for every company:** T-35-specific names and rules were removed. The old "T-35 Settings" is now the optional "Status List Rules". Settings of existing installations are preserved.
- **Install on my server guide:** The steps on the server and on the computer are shown one by one. "Test connection" marks which step is ready.
- **Project deletion:** Instead of typing the project name, a confirmation window appears.
- **Purchasing, sales and invoice documents:** Company details are printed on the documents.

## What's new in 1.5.3

- **Project deletion:** An administrator can delete a project permanently with the "Delete" button on the Projects page. The window shows with numbers what will be deleted and what will remain, asks for the project name and takes an automatic backup before deleting. "Archive" stays as it is.
- **BOM version deletion:** Rejected or undone BOM versions are removed with "Delete version". Approved versions are not deleted.
- **Select all:** Lists with selection have "Select all", "Invert" and "Clear selection". Shift-click selects all rows in between.
- **Drawing upload:** Files are now listed first; unwanted ones are unticked and then sent with "Upload selected".
- **Bulk drawing deletion:** In Drawings, multi-select is available in list and gallery view, including for unmatched drawings, with "Delete selected".

## What's new in 1.5.2

- **Fix:** A BOM file opened and saved in Excel no longer gives the "invalid level '1.Jan'" error. Levels and weights that Excel turned into dates are corrected back automatically and shown as a warning in the BOM version.

## What's new in 1.5.1

- **New list cards:** In the Parts list, stock and other lists every record is a tidy block: part number and type on top, status badge on the right, labelled field boxes below. On phones the part number stays on one line and the status badge moves to the next line.
- **Modern filter:** The filter panel has columns on the left and values on the right (a bottom sheet on phones). Next to the values you see how many records there are; "Contains text" and value search are in one place.
- **Active filters:** Shown as chips under the search bar. Tapping a chip edits the filter, ✕ removes it, "Clear all" removes them all.
- **Clean toolbar:** The search box has an icon and a clear button. On phones the top buttons scroll sideways in one row.
- **Fix:** In table view the filter popup on a column header no longer opens clipped.

## What's new in 1.5.0

- **Install on my server:** A new option on the first screen of the Windows app. Enter the address and SSH details of a Linux server (Ubuntu, Debian, Rocky, Alma, Fedora); LAB ERP is installed on the server automatically, runs as a service that starts on boot, and this computer connects to it. Running it again updates the server and keeps the data.
- **Staff privacy:** Only the admin and the people you grant that permission to see the staff and time screen (hourly rates included). Each employee sees only their own card and hours on the "My staff card" screen. A staff card is linked to a user account in the Staff tab.
- **Permissions by job:** Default roles were tightened. Invoices and payments are admin-only. Sales is only in the Planning/Purchasing role (view). Designers and viewers do not see contacts. In project cost, labour appears as a single anonymous line to those without staff permission. An administrator can grant permission per user if needed.
- **Windows look:** The white menu bar was removed. The app menu (reload, connection settings, data folder, update, close) opens in the top bar matching the theme. The window title bar is coloured for the light, dark and black themes.

## What's new in 1.4.1

- **New name: LAB ERP.** A new logo; the same name and icon on Windows, Android and the browser. Data and settings stay as they are.
- **Fix:** On a new computer the Windows app no longer gets stuck on the "opening" screen at first launch.
- If startup takes long, an "Open connection settings" button appears.

## What's new in 1.4.0

- **Create account:** An account request is sent from the sign-in screen. The administrator approves or rejects it in Administration › Users by giving a role and permissions; the number of pending requests is shown in the menu.
- **E-mail:** An e-mail address can be added to users. Administration › E-mail has ready-made settings for Gmail, Outlook and Yandex, plus a test e-mail. Lists and Excel files are sent by e-mail in one click; on a phone they are shared via Gmail/WhatsApp.
- **New list view:** The Parts list, stock and other lists default to card view; no sideways scrolling on phones, comfortable scrolling, search, filter and sort. The "Table" button switches to the spreadsheet-like view.
- **Parts list:** A simplified toolbar (Show, Excel / e-mail, Import menus).
- **Connection:** If the server address changes, the Windows app finds the server on the network itself. The installation adds a Windows Firewall rule.
- **Fix:** The "New version available" warning no longer appears on the current version and can be dismissed.
- **Installation guide:** Step-by-step installation with INSTALL.md.

## What's new in 1.3.1

- **Android:** Separate APK files per processor (arm64-v8a, armeabi-v7a, x86_64, x86) and a universal APK that works on every phone.
- **Update:** On a new version the app picks the APK suitable for the phone itself.

## What's new in 1.3.0

- **Android app:** Finds the server on the network itself and remembers the last server. Downloads are saved to the Downloads › LAB ERP folder, the camera can be used when adding a photo, and the back key closes dialogs and the menu.
- **Phone-friendly interface:** Slide-out side menu, bottom-sheet dialogs, scrollable tables and large touch areas on phones.
- **My profile:** Every user can change their own name and password by tapping their name in the top right.
- **Security:**
  - Failed sign-in attempts are rate limited.
  - Changing the password closes sessions on other devices.
  - Passwords are at least 8 characters.
  - A weak session key is replaced with a strong one automatically.
  - Uploaded files are served securely.
  - Protection against Excel formula attacks and corrupt or oversized files was added.
  - Browser security headers were added.

## What's new in 1.2.0

- **Part photos:** Several photos in the part detail and on the stock card; drag and drop, camera on phones, captions.
- **Thumbnails:** A "Gallery" view on the Drawings screen; PDFs and images are listed with large thumbnails.
- **New viewer:** Full screen on click; zoom with the wheel or two fingers, pan by dragging, double click, rotate, ← → for the next image.
- **Chat:** Direct and group messaging, sending files and images (drag and drop, paste), read markers, unread counter and notifications.

## What's new in 1.1.0

- **Live sync:** Changes made on devices on the same network appear on all open screens within seconds. A "Live" indicator is shown in the top bar.
- **User permissions:** Administration › Users gives each user None / View / Edit permission per module.
- **New home page:** Summary tiles, items needing attention, a transaction chart and recent transactions.
- **Sales and quotations:** Quotations and sales orders, discount, VAT, an Excel quotation form, invoice from order.
- **Invoice and payment:** Sales and purchase invoices, collections and payments, payment term tracking, account balance and statement.
- **Staff and time:** Staff cards and work hours written to a project; labour cost is added to the project.
- **Contacts:** Customer firm type and firm balance.
- **New interface:** Grouped, collapsible side menu, icons and clean page headers.

## Installation

- On first launch, choose "This computer is the server" or "Connect to the server on the network".
- In server mode the data is kept in the chosen folder (default Documents\ParcaTakipERP) and backed up every night. If the firewall asks, allow it for Private networks.
- In client mode the "Search the network for a server" button finds servers on the network.
- The app checks for a new version itself at startup; "Check for updates" is also in the menu.
