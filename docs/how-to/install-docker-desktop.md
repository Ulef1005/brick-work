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

1. **`compose.yaml`** tells Docker which Brick Work to run. Open [compose.yaml of release 1.0.0](https://raw.githubusercontent.com/Ulef1005/brick-work/v1.0.0/compose.yaml), save it with **Save page as** into the `brick-work` folder, and check that the name is exactly `compose.yaml`, not `compose.yaml.txt`.
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

Open a terminal in the `brick-work` folder: on Windows, **Terminal** or **PowerShell** (in File Explorer, right-click the folder and choose **Open in Terminal**); on a Mac, **Terminal** (right-click the folder in Finder, **Services → New Terminal at Folder**). Then type these three lines, one at a time:

```sh
docker compose pull
docker compose run --rm --entrypoint brickwork brickwork setup
docker compose up -d
```

The first line downloads Brick Work (under 1 GB, once). The second creates your empty collection and prints `setup: ok`. The third starts it in the background.

## 5. Open it

Open [http://localhost:3333](http://localhost:3333) in your browser and sign in with your password. The first page offers **Download the catalogue**, which needs no key; then add a set by its number and [check its parts](check-set-parts.md). If you already track your sets elsewhere, [bring them in](migrate.md).

Brick Work keeps running while Docker Desktop runs. To stop it, type `docker compose down` in the same folder; `docker compose up -d` starts it again.

## When something goes wrong

- **`docker: command not found`** or **cannot connect to the Docker daemon:** Docker Desktop is not running. Start it and wait for the engine.
- **`no configuration file provided`:** the terminal is not in the `brick-work` folder, or the file is called `compose.yaml.txt`.
- **The server refuses to start, asking for a password:** `data/.env` is missing, misnamed (`.env.txt`), or has no `BW_AUTHENTICATION_PASSWORD=` line.
- **Port 3333 is in use:** another program uses it. In `compose.yaml`, change `"127.0.0.1:3333:3333"` to `"127.0.0.1:3334:3333"` and open `http://localhost:3334`.
- **Logs:** `docker compose logs brickwork` shows what Brick Work printed.

## Next steps

- [Back up and restore](back-up-and-restore.md): copy the `data` folder regularly.
- [Upgrade Brick Work](upgrade.md): a new release means a new `compose.yaml`, then `docker compose pull` and `docker compose up -d`.
- Reaching Brick Work from your phone, or installing it on the Home Screen, needs it on your network with HTTPS: see **Standalone installation with Docker** in the [README](https://github.com/Ulef1005/brick-work#standalone-installation-with-docker).
