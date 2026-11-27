---
audience: user
verified: 1.0
---

# Install on your computer with Docker Desktop

*Since 1.0.0.*

For a Windows or Mac computer, with no Git and no server. You need about 15 minutes, an internet connection and a few GB of free disk space for Docker Desktop and Brick Work. Brick Work then runs on this computer only, in your browser.

Tested on macOS with Docker Desktop 4.75. On Windows the steps are the same, typed in PowerShell; a test on a real Windows computer is not recorded yet.

## 1. Install Docker Desktop

Docker Desktop runs Brick Work in a container, a sealed box with everything it needs.

1. Download Docker Desktop from [docker.com](https://www.docker.com/products/docker-desktop/) and install it. On Windows, accept the WSL 2 option the installer offers.
2. Start Docker Desktop and wait until it says the engine is running.

Docker Desktop is free for personal use; check its terms if you use it at work.

## 2. Make a Brick Work folder

1. Make a folder called `brick-work`, for example in your Documents folder.
2. Inside it, make a folder called `data`. Everything Brick Work keeps (your collection, photos, the catalogue) goes into `data`. This is the folder you back up.

## 3. Add two files

1. **`compose.yaml`** tells Docker which Brick Work to run. Open [compose.yaml of release 1.2.0](https://raw.githubusercontent.com/Ulef1005/brick-work/v1.2.0/compose.yaml), save it with **Save page as** into the `brick-work` folder, and check that the name is exactly `compose.yaml`, not `compose.yaml.txt`.
2. **`data/.env`** holds your settings. Make a plain text file in the `data` folder with this one line, using a password of your own:

    ```
    BW_AUTHENTICATION_PASSWORD=choose-a-long-password
    ```

    Save it with the name `.env` (a dot, then `env`, no other ending). In Windows Notepad, choose **Save as type: All files**, or Windows adds `.txt`. On a Mac, TextEdit needs **Format → Make Plain Text** first; Finder hides names that begin with a dot, and **Cmd+Shift+.** shows them.

The folder now looks like this:

```
brick-work/
  compose.yaml
  data/
    .env
```

## 4. Start Brick Work

Open a terminal in the `brick-work` folder:

- On Windows, **Terminal** or **PowerShell** (in File Explorer, right-click the folder and choose **Open in Terminal**).
- On a Mac, **Terminal** (right-click the folder in Finder, **Services → New Terminal at Folder**).

Then type these two lines, one at a time:

```sh
docker compose pull
docker compose up -d
```

The first line downloads Brick Work (under 1 GB, once). The second starts it in the background; on first start, the container creates your empty collection automatically.

## 5. Open it

Open [http://localhost:3333](http://localhost:3333) in your browser and sign in with your password. The first page offers **Download the catalogue**, which needs no key; then add a set by its number and [check its parts](check-set-parts.md). If you already track your sets elsewhere, [bring them in](migrate.md).

Brick Work keeps running while Docker Desktop runs. To stop it, type `docker compose down` in the same folder; `docker compose up -d` starts it again.

## When something goes wrong

- **`docker: command not found`** or **cannot connect to the Docker daemon:** Docker Desktop is not running. Start it and wait for the engine.
- **`no configuration file provided`:** the terminal is not in the `brick-work` folder, or the file is called `compose.yaml.txt`.
- **The server refuses to start, asking for a password:** `data/.env` is missing, misnamed (`.env.txt`), or has no `BW_AUTHENTICATION_PASSWORD=` line.
- **Port 3333 is in use:** another program uses it. In `compose.yaml`, change `"127.0.0.1:3333:3333"` to `"127.0.0.1:3334:3333"` and open `http://localhost:3334`.
- **Logs:** `docker compose logs brickwork` shows what Brick Work printed.

## With Git, or on a NAS

On Unraid, a Synology NAS or Portainer you need no Git: see [Install on Unraid](install-unraid.md) and [Install on a NAS or with Portainer](install-nas.md).

With Git and Docker Compose installed, the [README](https://github.com/Ulef1005/brick-work#install) has the short install: clone the release tag, make `data/.env` and start it.

The clone is still needed there: it holds `compose.yaml` and `.env.sample`. `docker compose pull` fetches the published image `ghcr.io/ulef1005/brick-work:VERSION`, built for amd64 and arm64. `docker compose build` builds the same image from the source you cloned instead. [Upgrade Brick Work](upgrade.md#move-to-the-new-version) shows how to check the image's provenance and its SBOM. Releases up to 0.9.0 build from source: their `compose.yaml` does not pull.

The container runs as uid 1000 and writes only to `data/`. With Git, give that user the folder with `sudo chown 1000:1000 data`; as root, leave out `sudo`. If an older image, which ran as root, created that folder, run `sudo chown -R 1000:1000 data` once.

For NAS users whose shared folder is not owned by uid 1000, set `user: "<uid>:<gid>"` in `compose.yaml` instead of changing ownership. With `docker run`, use `--user <uid>:<gid>`. Use the folder owner's ids; Unraid uses `99:100`.

The `data` volume holds the database, the local catalogue index, photos, PDFs and job state. Back it up together with your environment configuration. No separate application or service is required. The offline smoke test covers a fresh installation without source credentials.

Pictures and PDFs can live elsewhere, for example on a NAS: see [Settings](../reference/settings.md#storage-and-media).

## Reach Brick Work from your network

`compose.yaml` publishes the port on this computer only (`127.0.0.1:3333`). Once a password is set, change that to `3333:3333` to reach the app from your network.

Brick Work is for a home network or a VPN, not the open internet. Installing it on the Home Screen of a phone needs HTTPS. Set `BW_TRUSTED_PROXIES` and `BW_SECURE_COOKIES` when a reverse proxy serves it: see [Settings](../reference/settings.md#login-and-security).

## Next steps

- [Back up and restore](back-up-and-restore.md): copy the `data` folder on a regular schedule.
- [Upgrade Brick Work](upgrade.md): a new release means a new `compose.yaml`, then `docker compose pull` and `docker compose up -d`.
- [Reach Brick Work from your network](#reach-brick-work-from-your-network): from your phone, or installed on the Home Screen, which needs HTTPS.
