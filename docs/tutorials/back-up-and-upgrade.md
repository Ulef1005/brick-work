---
audience: user
verified: 1.0
---

# Back up, upgrade and restore

Your collection is worth more than the time it takes to protect it. In this tutorial you make a backup, move Brick Work to a new version and check that everything came along. Then you rehearse a restore, so you know it works before you need it, and take back a single wrong edit with Undo.

It takes about 30 minutes. You need a Brick Work install with the Docker setup from [Install Docker Desktop](../how-to/install-docker-desktop.md). You also need a collection with at least one set and a terminal open in the folder that holds `compose.yaml`. Version numbers below are examples; yours will differ.

## 1. Make a backup

A backup has three parts: a copy of the database, your `secret.key` and the media folders.

1. Open **Manage → Tools & Admin → Maintenance → Backup and database check** and select **Export database**.
2. Keep the downloaded `brickwork.db` somewhere outside the Brick Work folder, for example on an external drive. You do not need to stop Brick Work first.
3. Copy `secret.key` and the `data/` folders `images`, `thumbs`, `instructions` and `identifications` to the same place. Copy your settings file `data/.env` too.

The export leaves out your source keys, the catalogue and the media. Keep your BrickLink, Rebrickable and Brickset keys somewhere safe so you can enter them again. The catalogue can be built again from Rebrickable's files. [Back up and restore](../how-to/back-up-and-restore.md) explains each part.

## 2. Check the database before you change anything

1. On the same page, select **Run integrity check**.
2. Wait for **Database checks passed**. The page also lists the time of the check and the rows in each table.
3. Write down how many sets you own. You compare it after the upgrade.

If the page says **Database needs attention**, stop here and fix that first. A backup of a damaged file is a damaged backup.

## 3. Read what the new version does

1. Open the [changelog](https://github.com/Ulef1005/brick-work/blob/main/CHANGELOG.md) and find the entry for the version you want.
2. Open the table in [Upgrade Brick Work](../how-to/upgrade.md) and find your row. Look at the **Going back** column.

Some upgrades change the schema and cannot be reversed by starting the old version. Your backup from step 1 is the way back for those. An upgrade from 0.5.x to 0.6.0 is the one you run yourself with `brickwork migrate4`, and [Upgrade Brick Work](../how-to/upgrade.md#from-05x) has its steps.

## 4. Upgrade

1. In your terminal, fetch the releases and check out the tag you want:

    ```sh
    git fetch
    git checkout v1.1.1
    ```

2. Pull the new image and restart. Up to 0.9.0 the setup builds from source, so run `docker compose build` instead of `docker compose pull`:

    ```sh
    docker compose pull
    docker compose up -d
    ```

3. Wait a few seconds for Brick Work to start. Your `data/` folder stays where it is.

An upgrade that changes the schema runs on its own when the app first starts read/write. A step that fails leaves the file at the version before it.

## 5. Check the result

1. Open `/api/v2/health` on your address, for example `http://localhost:3333/api/v2/health`. It needs no token. Read the app version and the schema, for example `"app": "1.1.1"` and `"schema": "4.6"`.
2. Run the check from the terminal:

    ```sh
    docker compose exec brickwork brickwork check
    ```

   It prints the same checks as the page and ends with an error status when one fails. You can also use **Run integrity check** again.
3. Open **Sets** and compare the count with the number you wrote down in step 2.

If all three agree, the upgrade is done.

## 6. Rehearse a restore

Brick Work has no restore button. A restore means putting the snapshot back by hand. Practise it now, while nothing is wrong.

1. Stop Brick Work:

    ```sh
    docker compose down
    ```

2. Move the current `brickwork.db` aside, for example to `brickwork.db.rehearsal`, together with `brickwork.db-wal` and `brickwork.db-shm` if they exist. Do not delete it. It holds everything you did since the backup.
3. Put the exported `brickwork.db` and the matching `secret.key` in its place.
4. Start Brick Work again with `docker compose up -d` and run the check from step 5.
5. Open **Sets**. The count is the one from your backup. Changes made after the backup are not in it.
6. To return to the real state, stop Brick Work, move `brickwork.db.rehearsal` back to `brickwork.db` and start it again.

To go back to an older version for real, you must also check out its tag and refresh the image before you start it. Otherwise Docker starts the newer image again and upgrades the restored file once more. [Upgrade Brick Work](../how-to/upgrade.md#go-back) has the steps. If an older version says a file must be migrated, do not run `migrate4` on it. Restore the backup instead.

## 7. Undo a single wrong edit

A backup is for big mistakes. For one wrong edit, Undo is faster.

1. Open a set you own and change its note, then save. The notice that confirms the save ends in **Undo**.
2. Select **Undo**. The change is reversed and recorded as a new event.
3. Change it again if you meant it. An Undo cannot be undone itself.

If a later save touched the same rows, Brick Work refuses with a message such as **Item changed · undo the later save first**. Undo the later change first. Undo cannot take back a price lookup or a change already sent to Rebrickable or Brickset. For those, the backup is your safety net. An import or a pull can be undone from its own page, but only while nothing it made has changed since.

## What next

You made a backup, upgraded, checked the result, rehearsed a restore and used Undo. From here:

- [Back up and restore](../how-to/back-up-and-restore.md) for the API export and what each backup part holds.
- [Upgrade Brick Work](../how-to/upgrade.md) for the version table and how to verify the published image.
- [Undo a change](../how-to/undo-a-change.md) for every place Undo appears and the API.
- [Settings and maintenance](../how-to/settings-and-maintenance.md) for the catalogue and the checks.
