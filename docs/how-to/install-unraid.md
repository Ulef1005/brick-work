---
audience: user
verified: 1.1
---

# Install on Unraid

*Since 1.1.*

Brick Work is in Unraid's Community Applications. You install it from the **Apps** tab like your other containers, with no Git and no command line. You need an Unraid server with Docker switched on and about 15 minutes.

**What this guide was tested on.** The steps below follow the Community Applications template, which sets the image, the port, the data folder and the user. The same image was run on plain Docker (Docker 29 on macOS, release 1.1.1). It started on an empty data folder, created its own collection and answered its health check. Nobody has run these steps on a real Unraid server yet; the real Unraid check is tracked in [issue 529](https://github.com/Ulef1005/brick-work/issues/529).

## 1. Find it

1. Open the **Apps** tab of your Unraid web interface. If you have not used Community Applications before, Unraid offers to install it first.
2. Search for **Brick Work** and choose **Install**.

## 2. Fill in the fields

The template shows three fields. Change only the password.

| Field | Value | What it is |
|---|---|---|
| **WebUI port** | `3333` | The port of the web interface and the API. Change it if another container uses 3333. |
| **Data** | `/mnt/user/appdata/brick-work` | Your collection, the catalogue, photos and PDFs. This is the folder to back up. |
| **Password** | one of your own | The password you sign in with. Without one the server refuses to start. |

The template also runs the container as user `99:100` (`nobody:users`), the owner of Unraid's appdata folders. Choose **Apply**. If the log then says the folder is not writable, see [When something goes wrong](#when-something-goes-wrong).

## 3. Open it

When the container shows as started, select its icon and choose **WebUI**, or open `http://<your server>:3333`. Sign in with your password. On the first start the container creates your empty collection on its own. The first page offers **Download the catalogue**, which needs no key; then [add a set and check its parts](check-set-parts.md). If you already track a collection elsewhere, [bring it over](migrate.md).

Brick Work is for a home network or a VPN: do not forward its port to the internet.

## Keeping it up to date

The template uses the image tag `latest`, so Unraid offers each new release on the **Docker** tab. Read the [upgrade guide](upgrade.md) first and back up the **Data** folder before you update. To stay on one release, edit the container and put its version after the repository name, for example `ghcr.io/ulef1005/brick-work:1.1.1`. The upgrade guide's Git steps do not apply to you.

## When something goes wrong

- **The container stops at once, and its log asks for a password:** the **Password** field is empty. Edit the container, fill it in and apply.
- **It cannot write its folder:** the **Data** folder is not writable for user `99:100` (`nobody:users`). Docker can create a missing folder owned by root. Make the folder yourself in the Unraid file manager and give it to `nobody:users`, then start the container again.
- **Port 3333 is in use:** change **WebUI port** and open the new port.
- **Logs:** the container's menu on the **Docker** tab has **Logs**.

For a plain `compose.yaml` instead, see [Install on a NAS or with Portainer](install-nas.md).
