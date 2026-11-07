<div align="center">

<img src="frontend/public/logo-192.png" width="96" alt="LAB ERP logo">

# LAB ERP

**An ERP for manufacturing companies that runs on your own server.**<br>
Projects, BOMs, technical drawings, purchasing, stock, work orders, sales, finance and staff in one place.

[![Latest version](https://img.shields.io/github/v/release/serdevir91/parca-takip-erp?label=version&color=2563eb)](https://github.com/serdevir91/parca-takip-erp/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/serdevir91/parca-takip-erp/total?label=downloads&color=16a34a)](https://github.com/serdevir91/parca-takip-erp/releases)
![Windows](https://img.shields.io/badge/Windows-10%2B-0078d4)
![Android](https://img.shields.io/badge/Android-8.0%2B-3ddc84)
![Linux](https://img.shields.io/badge/Linux-server-f59e0b)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue)](LICENSE)

[**Download for Windows**](https://github.com/serdevir91/parca-takip-erp/releases/latest) ·
[**Download for Android**](https://github.com/serdevir91/parca-takip-erp/releases/latest) ·
[**Installation guide**](INSTALL.md)

[![Open in Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/serdevir91/parca-takip-erp?quickstart=1)

<br>

<img src="docs/screenshots/home.png" width="860" alt="Home: the day's summary, items that need attention and recent activity">

</div>

## Why LAB ERP?

- **Your data stays with you.** It runs on your local network without internet. There is no cloud account or monthly fee.
- **It is easy to install.** Make a Windows computer the server, or install it on your own Linux server from inside the app.
- **It fits your company.** Name, logo, currency, VAT, document numbers, security rules and modules are changed in the Administration screen.
- **Everyone works at the same time.** A change made on one device appears on the other screens within a few seconds.

## Screens

<table>
<tr>
<td width="50%"><img src="docs/screenshots/parts.png" alt="Parts list"><br><b>Parts list.</b> Tree or flat list, Excel-like filters, bulk editing.</td>
<td width="50%"><img src="docs/screenshots/bom.png" alt="BOM versions"><br><b>BOM versions.</b> Upload the SolidWorks list, then compare and approve versions.</td>
</tr>
<tr>
<td colspan="2"><img src="docs/screenshots/tree.png" alt="Product tree"><br><b>Product tree.</b> Build the product assembly by assembly without a CAD list; when you submit it, it becomes a BOM version.</td>
</tr>
<tr>
<td><img src="docs/screenshots/drawings.png" alt="Technical drawings"><br><b>Technical drawings.</b> Matches PDFs and images to parts automatically and checks the revision.</td>
<td><img src="docs/screenshots/planning.png" alt="Requirements and costs"><br><b>Requirements and costs.</b> See missing parts and turn them into orders and work orders.</td>
</tr>
<tr>
<td><img src="docs/screenshots/sales.png" alt="Sales and quotes"><br><b>Sales and quotes.</b> Turn a quote into an order and an order into an invoice.</td>
<td><img src="docs/screenshots/finance.png" alt="Invoices and payments"><br><b>Invoices and payments.</b> Track receivables, payables, collections and accounts.</td>
</tr>
<tr>
<td><img src="docs/screenshots/hr.png" alt="Staff and time"><br><b>Staff and time.</b> Working hours are posted to the project as labour cost.</td>
<td><img src="docs/screenshots/chat.png" alt="Chat"><br><b>Chat.</b> One-to-one and group messages with file attachments that stay inside the company.</td>
</tr>
<tr>
<td><img src="docs/screenshots/admin.png" alt="System settings"><br><b>System settings.</b> Company details, documents, security, backups and modules.</td>
<td><img src="docs/screenshots/home-dark.png" alt="Dark theme"><br><b>Three themes.</b> Light, dark and pure black (AMOLED).</td>
</tr>
</table>

### On the phone

The Android app finds the server on the network by itself. You can take photos and attach them to parts, and check stock and invoices in the field.

<p align="center"><img src="docs/screenshots/mobile.png" width="860" alt="Android screens: home, parts list, stock, invoices and payments"></p>

### Install on your own server

The **Install on my server** option in the desktop app connects over SSH and does the installation itself. The guide on screen
shows step by step what to do on the server and on the computer. The **Test connection** button marks any step that is not ready.

<p align="center"><img src="docs/screenshots/guide.png" width="560" alt="Install on my server guide"></p>

## What's included?

| Area | Features |
|---|---|
| **Engineering** | Project and BOM versions, product tree building, Excel-like table, advanced filters, bulk status changes, version comparison, part and fastener tracking, technical drawings, control list |
| **Production** | Assembly sheets and readiness, requirements analysis, work orders, operations and material consumption, stock cards and movements, barcodes and QR codes, automatic order suggestions, project costs |
| **Commercial** | Purchasing, supplier performance, contacts, quotes, sales orders, partial shipments and returns, invoices, collections and payments, TCMB exchange rates |
| **Team** | Staff cards, time entries, attendance tracking and correction requests, leave and sick notes, splitting attendance hours across jobs, chat, sharing by email |
| **Administration** | Per-module permissions, sign-up approval, audit log, notification center, automatic backups, restore from the screen, one-click HTTPS, project templates, system settings |
| **Platform** | Windows app, Android app, browser, Linux server with or without Docker |

## Try it now

Click the **Open in Codespaces** button above, then click "Create codespace". GitHub starts a machine in the cloud,
installs the app with demo projects and opens it in a new browser tab (the first start takes 3-5 minutes, later ones a few seconds).
Sign in with **admin / admin**. If the tab does not open, click the 🌐 icon next to port 8000 in the **PORTS** tab at the bottom.
A codespace stops by itself after 30 minutes without use; you can delete it at https://github.com/codespaces.

**If you are installing for the first time:** read [INSTALL.md](INSTALL.md) for step-by-step instructions
(server, clients, account approval, email setup, troubleshooting).

## Architecture

When the server is installed with Docker, the system consists of four containers:

| Service | Role |
|---|---|
| `db` | PostgreSQL 16 database (`pgdata` volume) |
| `backend` | API (FastAPI). Updates the database schema automatically on startup (`alembic upgrade head`) |
| `backup` | Takes a backup at the set time every day and deletes old backups |
| `frontend` | Web interface (nginx). Forwards `/api` requests to the backend and allows uploads of up to 2 GB |

No internet is needed while it runs. The interface uses no CDN; all files are inside the image.

## Contents

1. [Requirements](#requirements)
2. [Installation: Linux](#installation-linux)
3. [Installation: Windows](#installation-windows)
   - [Desktop app](#desktop-app-windows)
   - [Android app](#android-app)
4. [Docker-free installation](#docker-free-installation)
5. [Offline installation (server without internet)](#offline-installation-server-without-internet)
6. [First sign-in](#first-sign-in)
7. [ERP modules](#erp-modules)
   - [Photos and image viewer](#photos-and-image-viewer)
   - [Chat](#chat)
8. [Backup and restore](#backup-and-restore)
9. [Updating](#updating)
10. [Roles](#roles)
11. [Security](#security)
12. [Settings (.env)](#settings-env)
13. [Troubleshooting](#troubleshooting)
14. [Development](#development)
## Requirements

- A 64-bit server with at least 4 GB of RAM (8 GB recommended) and enough disk space for drawings and backups.
- Linux: Docker Engine 24+ and Docker Compose v2 (`docker compose`).
- Windows 10/11 or Windows Server: Docker Desktop (with the WSL 2 backend).
- Clients: a current version of Chrome, Edge or Firefox.

> The commands use `docker compose`. On older installations, use `docker-compose` (with a hyphen).

## Installation: Linux

```bash
# 1. Copy the project folder to the server, for example /opt/parca-takip
cd /opt/parca-takip

# 2. Create and edit the settings file (passwords and session key)
cp .env.example .env
nano .env

# 3. Build the images and start them (building needs internet and is done once)
docker compose up -d --build

# 4. Check the status: all must be "running", and db and backend must be "healthy"
docker compose ps
```

Open `http://SERVER_IP` in a browser (`http://SERVER_IP:PORT` if the port is not 80).

The services start automatically when the server restarts (`restart: unless-stopped`).
To make Docker start at boot: `sudo systemctl enable docker`.

If the firewall is on, allow the port, for example: `sudo ufw allow 80/tcp`.

## Installation: Windows

### Easy installation (recommended)

1. Install **Docker Desktop**: https://www.docker.com/products/docker-desktop/
   Keep "Use WSL 2 instead of Hyper-V" selected during installation. Restart the computer when it finishes.
   In the Docker Desktop settings, make sure "Start Docker Desktop when you sign in" is selected.
2. Download the project:
   - With Git: `git clone https://github.com/serdevir91/parca-takip-erp.git C:\ParcaTakip`
   - Without Git: on the GitHub page choose **Code > Download ZIP** and extract the ZIP to the `C:\ParcaTakip` folder.
   It is best to avoid Turkish characters and spaces in the folder path.
3. Double-click `C:\ParcaTakip\KURULUM.bat` and approve the administrator prompt.

`KURULUM.bat` does the following:

- Checks that Docker is installed and running, and starts Docker Desktop if it is not running.
- Creates the `.env` file on the first installation. The database password, session key and administrator password are generated at random.
- If port 80 is in use (IIS, Skype, etc.), picks a free port such as 8080.
- Builds the images and starts the system (the first installation needs internet and may take 5-10 minutes).
- Opens the port to the local network in Windows Firewall.
- At the end, shows the access addresses, the user name and the initial password, and opens the browser.

The same file is used for updates: copy the new version files into the folder and run it again.
`.env` and the data are kept.

Options (from PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows_install.ps1 -Demo        # with demo projects
powershell -ExecutionPolicy Bypass -File deploy\windows_install.ps1 -Port 8080   # specific port
```

### Manual installation

```powershell
cd C:\ParcaTakip
copy .env.example .env
notepad .env
docker compose up -d --build
docker compose ps
New-NetFirewallRule -DisplayName "Parca Takip ERP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

Note: Docker Desktop starts when a user signs in. If the server must run without anyone signed in,
set up automatic sign-in or choose the Linux installation.

**Common problems on Windows:**

- *"WSL 2 installation is incomplete"*: Run `wsl --install` in an administrator PowerShell and restart the computer.
- *Virtualization is off*: Turn on Intel VT-x / AMD-V (SVM) in the BIOS.
- *"In Windows container mode"*: Right-click the Docker icon in the system tray and choose "Switch to Linux containers".
- *Other computers cannot connect*: If the network profile is "Public", change it to "Private" and check the firewall rule.
  For company networks, see the [troubleshooting table in the installation guide](INSTALL.md#troubleshooting).

### Desktop app (Windows)

This is a Windows app that opens in its own window instead of a browser. You do not need Docker, Python or Node.

1. Download and run `LabERP-Setup-x.y.z.exe` from the
   [Releases](https://github.com/serdevir91/parca-takip-erp/releases/latest) page.
2. On first start there are two options:
   - **This computer is the server:** Data is kept in the chosen folder (default
     `Documents\LabERP`). For a new database, the administrator (`admin`) password is set on this screen. By default the app opens port 8000 and makes a backup every
     night. If Windows Firewall asks for permission, allow it for **Private networks**; otherwise other
     devices cannot connect.
   - **Connect to a server on the network:** The "Find server on network" button finds servers on the same network. You can also type the address
     by hand (for example `http://192.168.1.20:8000`).
3. Phones, tablets and other computers on the same network can also open the server address in a browser.
   The address is shown in **My profile** and in **Administration > System Settings**.

**Running in the background:** On the server computer, closing the window does not stop the server. The app moves to the hidden icons in the taskbar
(the ^ arrow next to the clock), and the other devices keep working. Click the icon to open the window
again. To shut the server down completely, right-click the icon and choose **Stop server and exit**.

**Live sync:** A change made on one device appears on the other open screens within a few seconds; you do not need to
reload the page. The "Live" indicator in the top bar shows the connection; if "No connection" appears, the server
is off or the network is down.

The app checks for a new version by itself on startup; the Administration page also has a "Check for updates" button.

### Android app

The Android app is for phones and tablets (Android 8.0 and later). The server still runs on a computer;
the app connects to the server on the same network.

1. On the phone, open the [Releases](https://github.com/serdevir91/parca-takip-erp/releases/latest) page,
   download `LabERP-x.y.z.apk` and open it. If Android asks for the "unknown sources" permission,
   give it to the browser. This file works on any phone. There are also processor-specific files:
   `-arm64-v8a` (most current phones), `-armeabi-v7a` (older 32-bit phones), `-x86_64` / `-x86`
   (emulators and some tablets).
2. On first start, the app searches for servers on the network by itself. Tap the server it finds or type the address by hand
   (for example `192.168.1.20:8000`). The phone must be on the same Wi-Fi network as the server.
3. Sign in with your user name and password. The last server you connected to is remembered.

- The menu opens with the ☰ button at the top left. The phone's back button closes the open window, the menu or the page.
- Excel, PDF and other downloads are saved to the phone's **Downloads › LAB ERP** folder.
- When adding a photo, you can choose the camera or the gallery.
- The server icon in the top bar, or "Change server" on the sign-in screen, switches to another server.
- The app checks for a new version on startup; if there is one, it opens the download page.

You can also use it in a phone browser without installing the app: just open the server address. The interface
adapts to phone screens.

## Docker-free installation

For computers that cannot run Docker (virtualization turned off, old Windows, etc.). The app runs in a single Python
process, the database is SQLite, and no extra server program is needed. This is enough for a team of 10-20 people.
For heavier use, the Docker installation (PostgreSQL) is recommended.

### Windows

1. Download the project (see [Installation: Windows](#installation-windows), step 2), for example to `C:\ParcaTakip`.
2. Double-click `KURULUM_DOCKERSIZ.bat` and approve the administrator prompt.

`KURULUM_DOCKERSIZ.bat` does the following:

- Installs Python 3.12 and Node.js with `winget` if they are missing (the first installation needs internet).
- Installs the Python packages and builds the web interface.
- Keeps the data in the `C:\ParcaTakipVeri` folder: the database (`erp.db`), uploaded files (`data`), backups
  (`yedek`), the log (`erp.log`) and a copy of the settings (`ayarlar.env`).
- Generates a random session key and administrator password; if port 80 is in use, picks a free port such as 8080.
- Registers a Task Scheduler task named `ParcaTakipERP`. The app starts when Windows boots, before anyone
  signs in, and restarts within 1 minute if it crashes. The daily backup runs every day at 02:00.
- Opens the port in the firewall and, at the end, shows the addresses and the initial password.

Options (from an administrator PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows_native_install.ps1 -DataDir D:\ParcaTakipVeri -Port 8080 -Demo
```

**Updating:** Copy the new version files to the project folder (or run `git pull`) and run `KURULUM_DOCKERSIZ.bat`
again. Data and settings are kept, and the schema is updated automatically.

**Management (administrator PowerShell):**

```powershell
Stop-ScheduledTask ParcaTakipERP                     # stop
Start-ScheduledTask ParcaTakipERP                    # start
Get-Content C:\ParcaTakipVeri\erp.log -Tail 50 -Wait  # follow the log
Unregister-ScheduledTask ParcaTakipERP               # remove automatic start (data stays)
```

`Stop-ScheduledTask` sometimes does not close the Python process. If `python.exe` remains in Task Manager,
it is closed when `KURULUM_DOCKERSIZ.bat` runs again.

**Manual backup and restore:**

```powershell
cd C:\ParcaTakip\backend
.venv\Scripts\python -m app.cli backup                 # backup: C:\ParcaTakipVeri\yedek
Stop-ScheduledTask ParcaTakipERP
.venv\Scripts\python -m app.cli restore erp_20261102_020000.tar --yes
Start-ScheduledTask ParcaTakipERP
```

If the backup file is not in `C:\ParcaTakipVeri\yedek`, give its full path. The Administration > Backup screen also works.

On Windows installations older than 1.5.11, backups did not complete. If the `yedek` folder contains only `erp_*.tar.partial`
files and `erp_bk_*` folders, move to 1.5.11 and take a manual backup. The new backup appears with the name `erp_*.tar`.
The old leftovers are deleted automatically when the retention period ends.
**Copy the backup folder to another disk regularly.**

### Linux / macOS

Python 3.12 and Node.js 20 must be installed:

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm ci && npm run build && cd ..
cd backend
cat > .env <<'ENV'
ERP_DATABASE_URL=sqlite:////srv/parca-takip/erp.db
ERP_DATA_DIR=/srv/parca-takip/data
ERP_BACKUP_DIR=/srv/parca-takip/yedek
ERP_JWT_SECRET=a-long-random-secret-key
ERP_ADMIN_PASSWORD=initial-password
ENV
.venv/bin/python -m app.cli serve --port 8080
```

To keep it running, define this command as a systemd service (`WorkingDirectory` = the `backend` folder).
If you want to use PostgreSQL, set `ERP_DATABASE_URL=postgresql+psycopg://user:password@server:5432/erp`.

## Offline installation (server without internet)

The images are prepared on a computer with internet and moved to the server as a single `.tar` file.

**1. On the computer with internet (Docker installed, in the project folder):**

```bash
# Linux / macOS
deploy/offline_export.sh 1.0.0
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File deploy\offline_export.ps1 -Tag 1.0.0
```

This command creates the `dist-offline/` folder:

- `parca-takip-images-1.0.0.tar`: backend, frontend and postgres images
- `parca-takip-images-1.0.0.tar.sha256`: checksum for detecting corruption
- `docker-compose.yml`, `.env.example`, `README.md`, `deploy/`

**2. Copy the `dist-offline` folder to the server with a USB disk.**

Docker must be installed on the server. If Docker itself must also be installed offline, download its installation packages
(`.deb`/`.rpm` packages for Linux, the Docker Desktop installer for Windows) separately and bring them over.

**3. On the server, inside the copied folder:**

```bash
# Linux
deploy/offline_import.sh
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File deploy\offline_import.ps1
```

On the first run, the `.env` file is created and the script stops. Change the passwords in the `.env` file,
then run the script again. The script loads the images (`docker load`), sets the `ERP_TAG` value
and starts the system (`docker compose up -d --no-build`).

## First sign-in

1. Open `http://SERVER_IP` in a browser.
2. Sign in with `ERP_ADMIN_USER` / `ERP_ADMIN_PASSWORD` from `.env` (the default for a manual installation is `admin` / `admin`;
   `KURULUM.bat` generates a random password and shows it at the end of the installation).
3. **Change the administrator password right away:** click your name at the top right and enter the new password in the **My profile** window
   (at least 8 characters).
4. Create users for the employees and give them roles (see [Roles](#roles)). Employees can also send a request themselves with
   **Create account** on the sign-in screen; the request is approved in Administration › Users.
5. Optional: set up the email server in Administration › Email (for sending lists by email
   and for account request notifications).
6. In Administration > Companies, check the manufacturer and supplier companies.
7. In Administration > Settings, check the part number patterns and the purchased assemblies.

The administrator account is created with the default values only when the database has no users at all.
Changing `.env` later does not change the existing password.

**If the administrator password is forgotten:**

```bash
docker compose exec backend python -m app.cli create-admin --username admin --password YeniSifre123
```

If the user does not exist, it is created. If it exists, it is made an active administrator and its password is reset.

**Demo data (optional):** Creates two demo projects with a sample BOM and status list:

```bash
docker compose exec backend python -m app.cli seed
```

In real use, archive the demo projects or do not run this command.

## ERP modules

Alongside part tracking there is a small manufacturing ERP. The flow: a BOM is uploaded, requirements are calculated, shortages
are covered from stock, by a purchase order or by a work order, and the cost is posted to the project.

- **Procurement types:** The built-in types are Manufacturing, Laser Cutting, Bending, Welding, Machining, Assembly, Painting,
  Heat Treatment, Purchased, Subcontracted manufacturing, Standard part, From stock, Customer-supplied and Unspecified. New ones
  are added in Administration > System Settings, or by an administrator during an Excel comparison. Each type behaves like Manufacturing
  or Purchased, and drawings and order suggestions are turned on or off separately.
- **Product tree Excel:** The product tree can be built from a file, matched with any Excel or CSV file and exported.
- **Control list fixes:** Issues that need a value have a Fix button, for one row or several selected rows.
- **Export:** Every table exports to Excel. Administrators can export all data, except users, settings and chat messages.
- **Project pictures:** A project can have a picture on its card.
- **Compare with Excel:** Any `.xlsx`, `.xlsm`, `.xls` or `.csv` file can be compared with the part list. Part number, status,
  order and procurement columns are found automatically and can be corrected. Changes are saved only after review.
- **Table:** Cell selection, ranges, copy and paste, fill handle, undo, find and replace, column
  hiding and pinning, conditional and advanced filters, saved views, `.xlsx` download. There are no formulas, charts or pivot tables.
- **Product tree** (project menu): Builds the BOM by hand for products that have no SolidWorks list. You start from the top
  product; parts and subassemblies are added under assemblies, and each row gets its quantity in the parent assembly, procurement type,
  material, weight and coating. The total quantity is shown multiplied out. When you pick a number used before,
  its details come with it, and for an assembly its child items too. You can also start from an existing BOM version.
  The draft is saved automatically. A submitted tree becomes a pending BOM version; comparison and approval are done as
  usual in the BOM versions screen.
- **Hide:** In the Parts list and Fasteners screens, the selected rows are hidden. The rows stay
  in the list and only appear dimmed; they are also dimmed in the Requirements & Costs screen. Quantities, status and requirement calculations
  do not change. In the tree view, the rows under a hidden assembly are dimmed too. The same button
  undoes it as "Unhide".
- **Parts list filter:** The "Show" buttons hide and show part, assembly, purchased assembly and fastener
  rows separately. In the tree view, the parent assemblies of matching rows are kept.
  The choice is remembered separately for each view.
- **Requirements & Costs** (project menu): For each part and fastener, the required, issued to the project,
  on order, in production and free stock quantities; the remaining shortage and the suggested action (cover from stock, purchase,
  open a work order). One click opens a draft order or work order from the selected shortages. The Costs tab shows committed
  and actual costs by source, company and main group.
- **Purchasing:** Orders numbered `SA-YYYY-####` (Draft, Sent, Partially received, Received,
  Cancelled), price, due date and delay warning per line, partial goods receipt, Excel order form.
  When an order is sent, its parts become "In progress" and its fasteners "Ordered"; when delivery is
  complete, they become "Completed" and "Delivered".
- **Work orders:** In-house or subcontracted work orders numbered `IE-YYYY-####`, production entry, unit cost.
- **Stock:** Stock cards (code, unit, shelf location, critical level), receipt, issue, count and issue-to-project
  movements, moving average cost, critical stock warning and movement history.
- **Home:** A summary of the modules the user can see: tiles for open orders, work orders, stock value, receivables and
  payables, items that need attention (late orders, critical stock, overdue invoices), a chart of activity over the last 30
  days and recent activity.
- **Contacts:** Customer, supplier and manufacturer companies; phone, email, address, tax details,
  lead time and current balance. The "Statement" button shows the company's invoice and payment movements with a running balance.
  When a supplier is chosen on an order, the due date is suggested from this lead time.
- **Sales and quotes:** Quotes and sales orders numbered `SS-YYYY-####` (Draft, Quoted,
  Confirmed, Delivered, Lost, Cancelled). Discount, VAT, validity and delivery date; Excel quote or
  order confirmation form. One click issues a sales invoice from a confirmed order.
- **Invoices and payments:** Sales invoices numbered `FT-YYYY-####` and purchase invoices entered with the supplier's number.
  A purchase invoice can also be created from a purchase order ("Enter purchase invoice"). Collections and
  payments are linked to an invoice or posted to the account (advance). Payment status (Unpaid, Partial, Paid,
  Overdue) and account balances per company.
- **Staff and time:** Staff cards (hourly cost) and working hours posted to a project or work order.
  Labour cost is added to the project's Costs tab with the source "Labour".
- **Attendance:** Employees clock in and out with a button, and the server records the time. Everyone sees only their own attendance. A manager with the `Attendance (all staff)` permission sees everyone, corrects records and exports them to Excel. Overtime is weekly; weekly hours and breaks come from System Settings. The employee's staff card must be linked to their account.

### Assembly sheets

The **Assembly sheets** page of a project prepares the day's assembly work on paper and on screen. It is built from the
approved BOM and the part list, so nothing is typed twice.

1. **Plan.** Choose **New plan**, pick the assemblies and single parts of the day, enter how many of each, and drag them
   into order. The order is the reservation order: scarce parts go to the upper row first. Save it as a draft, check the
   preview and publish it.
2. **Print.** **Print (PDF)** gives the daily plan, the pick list and one sheet per assembly in black and white. Each sheet
   can be followed by its drawings, or by a drawing list with QR codes. **Export to Excel** gives the same plan as a
   workbook with live formulas.
3. **Work in the workshop.** Sheets are marked by hand, or on the **Field entry** tab with the keyboard: arrows move
   between rows, keys 1, 2 and 3 set the status, and 4 marks a part as fitted.
4. **Bring it back.** **Upload Excel back** reads a filled workbook, shows every change and every error, and applies only
   what you select. **Upload photo** stores a photo of a marked sheet next to the field screen. The photo is not read
   automatically; enter its marks on the field screen.

**QR codes on the back.** Print the plan PDF double-sided. Every drawing page gets a QR page on its back, and every assembly
sheet gets one with a code for each step and for each part without a drawing page. Blank pages keep the codes on the back, and the
PDF asks for long-edge double-sided printing. In the **Drawings** page, **Print with QR** does the same for the selected drawings.

When the work is finished, scan the code on the back with the phone camera or **Scan barcode**. A confirmation screen opens with
the drawing, part and quantity. Nothing is saved until you press **Confirm**. A made part becomes **Made**, a bought part becomes
**Arrived**, and an assembly step is marked fitted and built. Reading the same code again adds nothing. Confirming needs edit
permission on `assembly`.

Part quantities replace plain statuses here: each part has a ready quantity, and a plan counts how many are left for each
assembly. An assembly with no shortage is reported as **ready to assemble** on the dashboard and in the notifications.
When you start using quantities, **Move from status to quantity** on the **Part quantities** tab counts parts shown as
completed as ready up to their BOM quantity and leaves other parts alone. **Mark completed** closes a published plan.

Extra quantities (a spare for the workshop, for example) are stored separately. They are reserved after the plan's needs, so
they never hold up an assembly. The **Consistency warnings** tab compares the plan, the pick list and the sheets, and the
**History** tab lists every change with who made it. Plans use the `assembly` permission module.

### Photos and image viewer

- **Part photos:** The part details (opened by clicking a row in the Parts list) have a "Photos" section.
  You can add as many photos as you like to a part number: select several files, drag files onto the section
  or tap "Take" on a phone to open the camera. Photos belong to the part number and appear in every project
  that uses the same part. Each photo can have a description.
- **Stock photos:** The stock card edit window has the same section.
- **Thumbnails:** In the Technical drawings screen, the "Gallery" button shows the images as cards with large thumbnails
  (PDF, PNG, JPG). The choice is remembered. The list view also has a preview column.
- **Viewer:** Clicking a thumbnail opens it full screen. Zoom with the mouse wheel or two fingers,
  pan by dragging, and double-click to enlarge. Use the ← → keys or the strip at the bottom to move to
  the other images in the same list. Images can be rotated (R), and there are 100% and "Fit to screen" buttons.
  PDF pages are turned in the same window.
- The photo upload limit is 50 MB. The browser makes the thumbnail, so the server takes no extra load.

### Chat

- In the menu: **System › Chat**. Private messages or group chats: the "New" button, then the "Direct" or
  "Group" tab.
- Files are sent with messages: the 📎 button, drag and drop, or paste from the clipboard (screenshots).
  Several files can be selected at once. Images appear as thumbnails in the message and open in
  the viewer when clicked; PDFs open with "View"; other files are downloaded. The file limit is 500 MB.
- The number of unread messages appears in the menu and in the browser tab title. When a new message arrives while you are on another
  screen, a notification appears. Messages reach the other side within a few seconds.
- Next to your message, one tick means sent and two ticks mean everyone has read it. You can delete your own message for
  everyone.
- The person who creates a group is its admin. The admin renames the group, adds or removes members and makes other
  members admins. If the last admin leaves, the oldest member becomes admin. A person added to the group later
  sees the earlier messages.
- Right-click a message or tap the arrow on it: reply, copy, forward, pin, edit (48 hours), select, delete.
  "Delete for me" removes it only from your screen; "Delete for everyone" removes the message for everyone. A group admin
  can also delete other people's messages for everyone and pin messages. Shortcuts: Esc cancels, the up arrow edits your last message.
- New messages and alerts arrive as system notifications in the Android and Windows apps. Android asks the server about every 30 seconds.
  With the screen off, this interval can grow to 10 minutes. The app must be able to reach the server.
- Files are kept in the server's data folder (`chat/`, photos in `photos/`) and are included in backups.

## Backup and restore

### Automatic backup

The `backup` service takes a backup every day at `ERP_BACKUP_TIME` (default 02:00).
The last `ERP_BACKUP_KEEP_DAYS` days (default 14) are kept and older ones are deleted. The latest backup is never deleted.

Each backup is a single file: `erp_YYYYMMDD_HHMMSS.tar`. It contains:

- `db.dump`: database dump (`pg_dump` custom format)
- `data/`: uploaded BOM files, technical drawings and thumbnails
- `manifest.json`: backup date, app version, file count

The backup file is readable only by its owner (0600). The session signing key is not included in the backup.

By default, backups are kept in the `erpbackups` Docker volume. **To protect against disk failure, also keep backups
on another disk.** To do this, set `ERP_BACKUP_PATH` in the `.env` file to a folder path
(for example `/srv/erp-yedek` or `D:/ERP-Yedek`) and run `docker compose up -d`.
On Linux this folder must be writable by the container user (uid 1000):
`sudo mkdir -p /srv/erp-yedek && sudo chown 1000:1000 /srv/erp-yedek`.

### Manual backup

- From the interface: Administration > Backup > "Back up now". Backups can be downloaded from the same screen.
- From the command line:

```bash
deploy/backup.sh               # take a new backup
deploy/backup.sh /mnt/usb      # take a backup and copy it to a USB disk
deploy/backup.sh --list        # list backups
```

```powershell
powershell -ExecutionPolicy Bypass -File deploy\backup.ps1 -CopyTo E:\Yedek
```

### Restore

A restore **overwrites** the current database and files. Back up the current state first.

In a Docker-free installation, the easiest way is the **Administration › Backups** screen: choose a backup from the list or upload a `.tar`
file. When the restore finishes, the session is renewed. In a Docker installation or from the command line:

```bash
# 1. Stop the backend and backup services so that users cannot make changes
docker compose stop backend backup frontend

# 2. If the backup comes from elsewhere, first copy it to the backup folder
#    (skip this step if the backup is already in the list)
docker compose run --rm --no-deps -v "$PWD:/import" backend cp /import/erp_20261102_020000.tar /backups/

# 3. Restore (the file name is the backup inside /backups)
docker compose run --rm backend python -m app.cli restore /backups/erp_20261102_020000.tar --yes

# 4. Start the services (if the schema differs, the backend updates it on startup)
docker compose up -d
```

In Windows PowerShell, write `${PWD}` instead of `$PWD` in step 2.

To see the contents of a backup file: `tar -tf erp_20261102_020000.tar`.

## Updating

Always take a manual backup before updating (`deploy/backup.sh`).

**On a server with internet:**

```bash
# Copy the new version files to the project folder (or git pull), then:
docker compose up -d --build
```

**On an offline server:**

1. On a computer with internet, run `deploy/offline_export.sh 1.1.0` with the new version.
2. Copy the `dist-offline` folder to the server. Keep the `.env` file on the server.
3. On the server, run `deploy/offline_import.sh` (Windows: `deploy\offline_import.ps1`).

The backend updates the database schema automatically on every start (`alembic upgrade head`); no manual step is needed.
Because the data lives in volumes, recreating the containers does not lose any data.

If something goes wrong, go back to the old version: set `ERP_TAG` in `.env` to the old version,
run `docker compose up -d` and restore the backup taken before the update.

**Warning:** The `docker compose down -v` command deletes the volumes, that is, **all data**. Do not use `-v`.

## Roles

| Role | What it can do |
|---|---|
| **Admin** | Everything. Managing users, companies and settings; audit log; backups. |
| **Designer** | Creating projects, uploading and approving BOMs, uploading technical drawings, updating status. |
| **Planning / Purchasing** | Updating production and material status, importing the status list, ordering fasteners. |
| **Viewer** | Viewing and exporting only. Cannot make changes. |

**Module permissions:** In Administration › Users, the administrator can give each user permissions
per module: **None** (not shown in the menu), **View** or **Edit**. The "Role" option uses the role's default.
Modules: Projects and BOM, Parts list, Fasteners, Technical drawings, Control list,
Requirements and costs, Purchasing, Work orders, Stock, Staff and time, Contacts, Sales, Invoices and payments,
Chat, Administration. Chat is on by default for every role; "View" can read messages but not write them. The Admin role always has full access. A change appears on the user's open screen within a few
seconds.

Rules:

- Users are not deleted but made inactive, so their names stay in the audit log.
- The last active administrator cannot be made inactive, and their role cannot be changed.
- An administrator cannot make their own account inactive or remove their own administrator role.
- Every change is written to the audit log: who, when, which field, old and new value.

**My profile:** Each user can change their own name and password by clicking their name at the top right. When the password
changes, the sessions on other devices are closed.

## Security

- **Passwords:** At least 8 characters. Passwords are stored with bcrypt.
- **Sign-in attempts:** Sign-in is blocked for a while after 5 failed attempts in 15 minutes from one address with one user name, 30 in total from one address, or 50 for one user
  name from all addresses. A single machine cannot lock out someone else.
- **Large requests:** A request without sign-in can be at most 1 MB, and a signed-in JSON request at most 64 MB.
- **Default password:** If the administrator still uses the `admin` password, a warning appears on every screen.
- **Sessions:** When a password is changed, the administrator resets a password or a user is made inactive, all of that user's
  open sessions are closed.
- **Session key:** If `ERP_JWT_SECRET` is empty, the default (`change-me`) or shorter than 32 characters, the app generates a random key
  (`.jwt_secret`) in the data folder and uses it.
- **Files:** Uploaded files are served only to signed-in users with permission. Files other than images and PDF
  do not open in the browser; they are downloaded. SVG is not accepted as a photo.
- **Excel:** In exported Excel files, formulas typed by users are turned into text. Oversized or
  corrupt Excel and ZIP files are rejected.
- **Browser:** The server sends security headers (CSP, `X-Frame-Options`, `nosniff`); the interface cannot be embedded
  in other sites.
- **HTTPS:** The **Administration › HTTPS** screen creates its own certificate on a Docker-free server and turns on HTTPS. The Android and
  desktop apps save the certificate on the first connection and refuse to connect if it changes later. While this setting is off, traffic
  travels unencrypted on the local network and the administrator sees a warning on screen. In a Docker installation, HTTPS is set up in the nginx configuration.
  Android does not connect over plain HTTP to a server that has moved to HTTPS. The desktop app checks the certificate on every connection,
  not only at sign-in. Live camera scanning needs HTTPS in the browser; over plain HTTP, scanning from a photo works.
- **Session cookie:** The session is kept in an httpOnly cookie that scripts cannot read. With HTTPS on, the cookie is sent only over
  encrypted connections. Android and the desktop app use a short-lived, single-purpose ticket when downloading files.
- **Sign-up:** **Create account** is off in new installations; the administrator turns it on in **Administration › Users**.
  In older installations the saved setting does not change; if it is on, the administrator sees a warning on screen.
- **Email:** The SMTP password is stored encrypted. The email module is now opened by permission.
- **Desktop updates:** The Windows app runs only installer files whose Ed25519 signature verifies.
- **API documentation** (`/api/docs`) is off by default; turn it on with `ERP_API_DOCS=true`.
- **Windows installation:** Only Administrators, SYSTEM and the user who ran the installation can access the `.env` and `ayarlar.env`
  files.

The app is designed for a local network. Do not expose it to the internet; if you need remote access, use a VPN.

## Settings (.env)

| Variable | Default | Description |
|---|---|---|
| `ERP_HTTP_PORT` | `80` | Port the interface is served on |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `erp` / `erp` / `erp` | Database credentials. Do not use the characters `@ : / ?` in the password. |
| `ERP_JWT_SECRET` | `change-me` | Session key. It must be long and random; if it is weak, the app generates one itself (see [Security](#security)). If it changes, everyone has to sign in again. |
| `ERP_ADMIN_USER` / `ERP_ADMIN_PASSWORD` | `admin` / `admin` | First administrator (first start only) |
| `ERP_BACKUP_TIME` | `02:00` | Daily backup time |
| `ERP_BACKUP_KEEP_DAYS` | `14` | Number of days of backups to keep |
| `ERP_BACKUP_PATH` | `erpbackups` | Backup location: volume name or folder path |
| `ERP_MAX_UPLOAD_MB` | `2048` | Largest upload |
| `ERP_API_DOCS` | `false` | If `true`, the `/api/docs` API documentation is available |
| `ERP_UPDATE_FEED_URL` | empty | Address of the version information on the local network (update notice) |
| `TZ` | `Europe/Istanbul` | Time zone |
| `ERP_IMAGE_PREFIX` / `ERP_TAG` | `parca-takip` / `latest` | Image name and version |

The backup time, backup retention, upload limit and session length saved in Administration > **System Settings**
take precedence over the `.env` values. A setting not changed on screen uses the `.env` value. Installation-specific values
(port, database, session key) are read only from the `.env` file.

`POSTGRES_PASSWORD` is written to the database on the first installation. Changing it later in `.env` is not enough.
First change it in the database too:
`docker compose exec db psql -U erp -c "ALTER USER erp PASSWORD 'new'"`.

## Troubleshooting

```bash
docker compose ps                 # service status
docker compose logs -f backend    # backend logs
docker compose logs --tail 50 backup
curl http://localhost/api/health  # health check, returns {"status": "ok"}
```

- **The interface opens but you cannot sign in:** Check the output of `docker compose logs backend`.
  If there is a database connection error, check the `POSTGRES_*` values in `.env`.
- **Large files do not upload:** Check the `ERP_MAX_UPLOAD_MB` value and the free disk space.
- **Backups are not taken:** Look at the output of `docker compose logs backup`. The Administration > Backup screen
  shows the last backup date and the free disk space.
- **Port 80 is in use:** Set `ERP_HTTP_PORT=8080` in `.env` and run `docker compose up -d`.

## Development

```bash
# Backend (with SQLite, no PostgreSQL needed)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
ERP_DATABASE_URL=sqlite:///./dev.db ERP_DATA_DIR=./data ERP_BACKUP_DIR=./backups \
  .venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest -q

# Frontend (http://localhost:5173, forwards /api requests to the backend)
cd frontend
npm ci && npm run dev

# Android app (needs JDK 17 and the Android SDK)
cd mobile/android
./gradlew assembleDebug      # app/build/outputs/apk/debug/app-debug.apk
./gradlew assembleRelease    # one APK per ABI + universal; signing: keystore.properties or ERP_KEYSTORE_*
```

Android releases must always be signed with the same key; otherwise phones cannot install the update.
On a `v*` tag, CI signs the APK with the `ERP_KEYSTORE_B64` (base64 `release.jks`), `ERP_KEYSTORE_PASSWORD`,
`ERP_KEY_ALIAS` and `ERP_KEY_PASSWORD` repository secrets; if the secrets are missing, it skips the APK step.

Command-line tools (`python -m app.cli`):

| Command | Description |
|---|---|
| `seed [--force]` | Creates demo projects from the sample files |
| `backup [--daemon --at 02:00]` | Takes a backup; with `--daemon`, every day at the same time |
| `restore FILE [--yes]` | Restores from a backup |
| `create-admin --username U --password P` | Creates an administrator or resets their password |
| `migrate` | Updates the database schema (`alembic upgrade head`) |
| `serve [--port 8000] [--no-backup]` | Docker-free run: schema update, web server (API + interface) and daily backup |

Database schema changes: after editing `backend/app/models.py`, create a migration with
`cd backend && .venv/bin/alembic revision --autogenerate -m "description"`.
Detailed requirements: `docs/SPEC.md`.

## Languages

The interface is available in Turkish, English, Spanish and German. Each user picks a language in the header or on the sign-in page, and dates and numbers follow that choice. Server messages and notifications use the same language. Stored data stays as it was entered, and the Excel tracking workbook stays Turkish because its formulas and the Excel import depend on that text.

## License

LAB ERP is free software, released under the [GNU General Public License v3.0 or later](LICENSE). You may use, study, change and share it. If you distribute a modified version, you must share its source code under the same license.
