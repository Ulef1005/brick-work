---
audience: user
verified: 1.1
---

# Install on a NAS or with Portainer

*Since 1.1.*

For a Synology NAS (Container Manager) or any Docker host you manage with Portainer. Another NAS with Docker works the same way: paste the file into its Docker or compose tool. You paste one file, set a password and start it: no Git, no download of the source and no `chown`. You need about 15 minutes. On Unraid, use the [Unraid guide](install-unraid.md) instead.

**What this guide was tested on.** The compose file below was run on plain Docker (Docker 29 on macOS, release 1.1.1). It pulled the image and started on an empty volume with no ownership change. It created its own collection and answered its health check. The steps in Container Manager and Portainer follow each vendor's documentation. They have not been run on a real device yet; the real checks are tracked in [issue 529](https://github.com/Ulef1005/brick-work/issues/529).

## The file to paste

```yaml
services:
  brickwork:
    image: ghcr.io/ulef1005/brick-work:1.1.1
    container_name: brickwork
    restart: unless-stopped
    ports:
      - "3333:3333"
    environment:
      BW_AUTHENTICATION_PASSWORD: change-this-to-a-long-password
    volumes:
      - brickwork-data:/app/data

volumes:
  brickwork-data:
```

Change the password before you start it. The image is built for amd64 and arm64. `brickwork-data` is a Docker volume, so the container can write to it whatever user it runs as. To change the port you open in the browser, change the first `3333`.

## Synology: Container Manager

1. Open **Container Manager** and choose **Project**, then **Create**.
2. Name the project `brick-work`, choose a path for it (for example a folder `docker/brick-work`), and as the source choose **Create docker-compose.yml**.
3. Paste the file above, change the password and finish the wizard.
4. Open `http://<your NAS>:3333` and sign in.

## Portainer

1. Choose your environment, then **Stacks**, then **Add stack**.
2. Name it `brick-work`, choose **Web editor** and paste the file above.
3. Change the password and choose **Deploy the stack**.
4. Open `http://<your host>:3333` and sign in.

## First start

On the first start the container creates your empty collection on its own. The first page offers **Download the catalogue**, which needs no key; then [add a set and check its parts](check-set-parts.md). If you already track a collection elsewhere, [bring it over](migrate.md). Brick Work is for a home network or a VPN: do not forward its port to the internet.

## Keep the data in a shared folder instead

A Docker volume lives inside Docker's own storage, which is hard to reach from the NAS file manager. To keep the data in a folder you can see and back up, replace the volume with a folder and tell Docker which user owns it:

```yaml
    user: "1026:100"                       # the owner of your folder: its user id and group id
    volumes:
      - /volume1/docker/brick-work/data:/app/data
```

Make the folder first, and use the ids of the account that owns it (on Synology, `id <user>` over SSH prints them). This variant has not been tested on a real device. You can also keep the pictures and PDFs on the NAS and the database on fast local storage: see [Settings](../reference/settings.md#storage-and-media).

## When something goes wrong

- **The container stops at once, and its log asks for a password:** the `BW_AUTHENTICATION_PASSWORD` line is missing or empty.
- **With a shared folder, it cannot write its data:** the `user:` ids do not match the folder owner.
- **Port 3333 is in use:** change the first number in `"3333:3333"` and open the new port.
- **Logs:** the container's page in your NAS or Portainer shows them.
- **Update:** see the [upgrade guide](upgrade.md), and back up the data first.
