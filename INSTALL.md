# Installation guide (the easy way)

This guide is for the person installing LAB ERP for the first time. Technical details and the Docker installation
are in [README.md](README.md).

The system has two parts:

- **Server:** The one computer that holds the data. It must stay on during working hours.
- **Client:** The other devices that connect to the server. These can be the Windows app, the Android app or
  any browser.

All devices must be on the same network (same modem / Wi-Fi). No internet connection is needed.

Downloads: the [Releases](https://github.com/serdevir91/parca-takip-erp/releases/latest) page.

| File | Purpose |
|---|---|
| `LabERP-Setup-x.y.z.exe` | Windows app (server or client) |
| `LabERP-x.y.z.apk` | Android app (runs on any phone) |

## 1. Install the server (once)

The easiest way is to make a Windows computer the server. You do not need Docker, Python or any other program.

1. Download and run `LabERP-Setup-x.y.z.exe`.
2. If the installer asks who to install for, choose **Install for all users** and approve the administrator prompt.
   This way the installer adds the Windows Firewall permission itself.
3. Open the app and choose **This computer is the server**.
4. Confirm the data folder (default `Documents\LabERP`).
5. Set the administrator (`admin`) password. Do not forget this password.
6. If Windows Firewall asks for permission, tick **Private networks** and click **Allow access**.
7. The screen shows the server address (for example `http://192.168.1.20:8000`). Write this address down.
8. Closing the window does not stop the server; the app moves to the hidden icons next to the clock. To shut the server
   down completely, right-click the icon and choose **Stop server and exit**.

Notes:

- The server computer's network must be **Private**: Settings › Network & Internet › Wi-Fi/Ethernet ›
  Network profile type › **Private**. If the network is "Public", other devices cannot connect.
- Giving this computer a fixed IP on the modem (DHCP reservation) keeps its address from changing. It is not required:
  if the address changes, the apps find the server again on their own.
- The server makes a backup every night. Backups are in the `backups` folder inside the data folder.

### Automatic installation on a Linux server (Install on my server)

If your company has a Linux server (Ubuntu, Debian, Rocky, Alma, Fedora; your own server or a cloud server), the Windows
app installs LAB ERP there by itself.

1. Install `LabERP-Setup-x.y.z.exe` on a Windows computer and open the app.
2. Choose **Install on my server**. If the app is already set up, return to this screen with **App › Connection settings**
   in the top bar.
3. Enter the server address (for example `192.168.1.50`), the SSH port (usually `22`), the SSH user name and the password.
   If the user is not `root`, it must have sudo rights; the same password is used for sudo.
4. Set the administrator (`admin`) password (at least 8 characters).
5. Click **Install and connect**. Progress is shown on screen; the installation takes a few minutes. When it finishes, this computer
   connects to the server. Other devices connect with `http://SERVER-ADDRESS:8000`.

Notes:

- The server must be able to reach the internet (Python packages are downloaded).
- The app is installed in `/opt/laberp`, and data and backups go to `/var/lib/laberp`. The `laberp` service starts on its own
  when the server boots. Status: `systemctl status laberp`, log: `journalctl -u laberp`.
- To update the server, repeat the same steps in the new version of the Windows app. If you leave the administrator password
  empty, the password does not change; the data is kept.
- The "Open this port in the firewall" box opens the port in ufw or firewalld on the server. On cloud servers
  you must also open the port (8000/TCP) in the security group in the provider's panel.
- To sign in with an SSH key, choose the private key file in the **Sign in with SSH key** section.

Manual installation on a Mac or Linux server: in [README.md › Docker-free installation](README.md#docker-free-installation),
the `python -m app.cli serve` command is all you need.

## 2. Connect the clients

### Windows

1. Install the same `LabERP-Setup-x.y.z.exe` file.
2. Open the app and choose **Connect to a server on the network**.
3. Press the **Find server on network** button and choose the server that appears. If none appears, type the address by hand
   (for example `http://192.168.1.20:8000`).
4. The app remembers this server. If the server address changes later, the app scans the network and, if it finds a single
   server, switches to it on its own.

### Android

1. Download and open `LabERP-x.y.z.apk` on the phone. If you are asked for the "Unknown sources" permission,
   allow it for the browser.
2. The app searches for the server on the network by itself. Tap the server it finds or type the address.
3. If you are asked for notification permission, allow it. New messages are notified even when the app is closed. The phone must be able
   to reach the server. If notifications arrive late, remove the battery restriction for LAB ERP in the phone settings.

### Browser

On any device, type the server address in the browser (for example `http://192.168.1.20:8000`).

**Finding the address later:** Sign in on any device that already works. The address is shown with a **Copy** button in
**My profile** and in **Administration > System Settings**. If several addresses are listed, try the first one first.

## 3. Account requests and approval

New employees request their own accounts, and the administrator approves them. This feature is off in new installations. The administrator first
turns on account requests in **Administration › Users**. If you do not want to turn it on, create the accounts yourself on the same screen.

**Employee:**

1. On the sign-in screen, press the **Create account** button.
2. Enter a user name, full name, email (optional) and password (at least 8 characters).
3. Click **Send account request**. The message "Your account request has been sent to the administrator" appears.
4. If you try to sign in before approval, the warning "Your account is waiting for administrator approval" appears.

**Administrator:**

1. Sign in as `admin`. The number of pending requests appears next to **Administration** in the left menu.
2. The **Pending account requests** list is at the top of the **Administration › Users** tab.
3. Press **Approve and grant permissions**. Choose the role (Viewer, Planning/Purchasing, Designer, Admin)
   and, if needed, change the module permissions one by one (None / View / Edit).
   Roles follow the job: Staff and time (hourly rates) and Invoices and payments are open only to Admin.
   If someone else needs one of them, open that module for the user separately.
4. Save. The employee can now sign in.
5. For an unwanted request, click **Reject**; the request is deleted.

Each employee sees only their own card and working hours on the **My staff card** screen. For this,
open the person's card in the **Staff and time › Staff** tab and choose their account in the **User account** field
(only the administrator sets this link; a matching email address no longer counts).

**Attendance:** Employees clock in and out on the **Attendance** screen in the menu and see only their own attendance.
To let a manager see everyone, open the **Attendance (all staff)** module: View lists everyone, Edit
adds and corrects records. Weekly working hours and break length are in System Settings.

Permissions can also be changed later on the same screen. To stop everyone from requesting accounts,
untick the **Show "Create account" on sign-in** box in the Users tab.

## 4. Email (optional)

Sending lists by email and emailing the administrator about new account requests need a one-time setup.

1. Open the **Administration › Email** tab.
2. Choose your email provider from the presets (Gmail, Outlook, Yandex, Yahoo) or enter your company server.
3. Enter the user name and password.
   - **Gmail:** Your normal password does not work. Turn on Google Account › Security › 2-Step Verification, then
     create a 16-character password under **App passwords** and enter it here.
   - **Outlook / Yandex:** If two-step verification is on for the account, you also need an app password.
4. Click **Save**, then **Send test email**.
5. Administrators must have an email address in their **My profile** window; new account requests are sent to this address.

Sending email requires the server to reach the internet. Everything else works without internet.

**Sending lists:** The **Share ▾** menu above the lists has **Send by email**. In the Parts
list, the **Excel / email ▾** menu attaches the Excel file to an email. On a phone, **Share from phone**
sends the file with Gmail, WhatsApp or Drive; this does not need email settings on the server.

## 5. Working with lists

- Lists open in **card** view by default: on a phone or narrow screen you do not need to scroll sideways.
- The **List / Table** button at the top right switches to an Excel-like table. The choice is remembered on the device.
- The **Search** box searches all columns. The **Filter** button opens the column filters. The arrow in a column header also offers conditions next to the value list: contains, equals, greater than, between, empty and similar.
- The **Advanced** button builds rule groups. Inside a group the rules are joined with AND or OR; the groups apply together. Filters, sorting and column layout are saved by name in the **Views** menu. Saved views are kept on that device.
- In table mode, click a cell and move with the arrow keys; start typing to edit. Select a range with the mouse or with Shift. Ctrl+C, Ctrl+X and Ctrl+V work both ways with Excel. Drag the handle in the corner to fill: 1, 2 or A1, A2 continue as a series. Ctrl+Z undoes, Ctrl+F finds, Ctrl+H replaces. The right-click menu offers the same actions. The status bar shows the sum and average of the selection.
- The **Columns** button hides, orders and pins columns. The Share menu downloads the rows and columns visible on screen as `.xlsx`.
- **Import > Compare with Excel** reads any `.xlsx`, `.xlsm`, `.xls` or `.csv` file and compares it with the part list. Check the changes, correct the columns under **Column mapping** if needed, then click **Apply**. Blank cells do not change anything.
- There are no formulas, charts, pivot tables, macros or selections of separate ranges. For these, download the list as `.xlsx` and open it in Excel.
- In the Parts list, filter and select rows, then change them all at once with **Set progress** or **Set procurement** in the bar at the top. This works in both modes.
- **Part name** is typed or pasted in the table. For many names, use **Import > Paste part names**: copy the part no and name columns from Excel. The name appears in every project where the same part number occurs.
- Procurement types are added under **Administration > System Settings**. For each type you choose separately how it behaves, whether it needs a drawing, and whether it gets order suggestions.
- On a card, editable fields have a dashed underline; tap them to change them. The ✎ button also shows empty fields.
- In the Parts list and Fasteners screens, select rows and click **Hide**: the rows stay in the list and only appear dimmed. Calculations do not change.

## Troubleshooting

| Symptom | Solution |
|---|---|
| "Find server on network" finds nothing | Is the app open on the server computer? Are you on the same Wi-Fi? Try typing the address by hand. |
| "Could not reach the server" | On the server, Windows Firewall must give "LAB ERP" (or Python) permission on **Private** networks. The network profile must be **Private**. |
| The phone cannot connect, the computer can | The modem may have "guest network" or "AP/client isolation" turned on; connect the phone to the main Wi-Fi network. |
| It connects at home, but other devices cannot connect on the work network | 1) Set the server computer's network profile to **Private**: Settings › Network & Internet › Wi-Fi or Ethernet › network properties. The firewall permission added during installation does not work on the **Public** profile. On a company computer, IT may have to do this. 2) The phone must be on the same Wi-Fi, not on a guest network or mobile data. 3) Try `http://<server-ip>:<port>` in the phone's browser; the address is shown in the menu of the LAB ERP icon next to the clock. Company networks often block automatic search, so type the address by hand. 4) If the browser cannot open it either, the network has client isolation or a blocked port; ask IT to allow this port. If IT allows it, a VPN such as Tailscale is also a solution. |
| Message notifications do not arrive | Android: is notification permission on, can the phone reach the server, are you signed in? Windows: check Windows notifications and the "Do not disturb" setting. The app must be running in the hidden icons next to the clock. |
| The address changed | The apps search for the server again on their own. If that fails, choose the new address with "Change server". Permanent fix: a fixed IP on the modem. |
| No **Create account** on the sign-in screen | The administrator must turn on account requests in Administration › Users. |
| Phone: "The server's certificate has changed" warning | The server's HTTPS certificate has changed. If you made the change, forget the server with "Change server" and connect again. If you did not, do not connect and check the network. |
| Phone: "This server uses HTTPS" warning | Connect to the server with `https://`. If HTTPS was turned off on the server, first remove the server from the Recently used list. |
| No live camera on the barcode screen | The browser does not open the camera over plain HTTP. Turn on HTTPS in Administration › HTTPS, or scan from a photo. |
| Everyone was signed out after moving to 1.5.10 | This is expected: sessions moved to a session cookie, so everyone signs in again once. |
| A project cannot be deleted permanently | Upgrade the Windows server to 1.5.11. In older versions the backup taken before deletion did not complete. |
| Backup failed, project not deleted | Read the reason on screen; usually the disk is full or the backup folder is not writable. A project deleted without a backup cannot be restored. |
| Expected working hours count a holiday | Add the holiday in Administration › Public Holidays. Religious holidays are entered by hand each year. |
| Sign-in: "Your account is waiting for administrator approval" | The administrator must approve it in Administration › Users. |
| Sign-in: "Your account is inactive" | The administrator has made the account inactive; it can be made active again in the Users screen. |
| Email: "did not accept the user name/password" | In Gmail, use an app password instead of your normal password. |
| "A new version is available" warning | Install the new version of the client app or reload the page. You can close it for that session with ✕. |
| Administrator password forgotten | On the server: `python -m app.cli create-admin --username admin --password YeniSifre123` |
