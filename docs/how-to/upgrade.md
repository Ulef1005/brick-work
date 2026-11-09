# Upgrade Brick Work

*Since 0.9.0.*

Do this when a new version is out and you want to move to it. Most upgrades need nothing from you: start the new version and it brings the collection along. The one exception is the move from 0.5.x to 0.6.0, which you run yourself.

## Before you upgrade

1. Back up. Export the database (**Manage → Tools & Admin → Database → Export database**) and copy `secret.key` and the media folders. [Back up and restore](back-up-and-restore.md) has the steps.
2. Read the entry for the new version in the [changelog](https://github.com/Ulef1005/brick-work/blob/main/CHANGELOG.md). It names any step you must take.

The backup is also the way back. An upgrade that changes the schema is one-way.

## What each version does

| From | To | Schema | What runs | Going back |
|---|---|---|---|---|
| 0.5.x | 0.6.0 | 3.3 to 4.0 | You run [`brickwork migrate4`](../reference/cli.md#migrate4) on a copy. It writes a new file and checks it before it publishes. The 3.3 file is never changed. | Keep the 3.3 file and start 0.5.x on it. |
| 0.6.0 | 0.7.0 | 4.0 to 4.1 | In place, at the first read-write start. | Restore the backup. 0.6.0 cannot open a 4.1 file. |
| 0.7.0 | 0.8.0, 0.8.1 | none (stays 4.1) | Nothing. | Start the older version on the same file. |
| 0.8.x | 0.9.0 | 4.1 to 4.2 | In place, at the first read-write start. | Restore the backup. 0.8.x cannot open a 4.2 file. |
| 0.9.0 | 1.0.0 | none (stays 4.2) | Nothing. | Start the older version on the same file. |

You can skip versions from 0.6.0 on. Starting 0.9.0 on a 4.0 file runs both in-place steps one after the other, each in its own transaction; a step that fails leaves the file at the version before it. From 0.5.x you always run `brickwork migrate4` first, and it writes the schema of the version you are moving to.

A read-only instance (`BW_READ_ONLY`) never upgrades a file. Start the new version read-write once, then switch.

If an older version refuses a newer file, its message may say a 3.3 file must be migrated. Do not run `migrate4` on a 4.x file: it reads only a 3.3 file. Restore the backup instead.

## From 0.5.x

1. Stop Brick Work 0.5.x, so that everything it wrote is in `brickwork.db` and not only in `brickwork.db-wal`. Then make a copy of the 3.3 `brickwork.db`. Never copy the file while the app runs.
2. Run `brickwork migrate4` on the copy, with the `catalogue.db` and the mapping files it needs. The arguments and the exit statuses are in [Commands](../reference/cli.md#migrate4).
3. Read the report folder. Rows that need a decision stop the run.
4. Put the new file in place as `brickwork.db`, beside `catalogue.db`, and start the new version.

## Move to the new version

With the Docker install, check out the release you want by its tag, then pull its image and restart. From 1.0.0 on, `compose.yaml` names the published image; up to 0.9.0 it builds from source, so use `docker compose build` there:

```sh
git fetch
git checkout v1.0.0
docker compose pull         # 0.9.0 and older: docker compose build
docker compose up -d
```

Your `data/` folder stays where it is. Without Docker, update the source the same way and restart the app.

From 1.0.0 on, you can check the published image before you start it, with the [GitHub CLI](https://cli.github.com/) and that release's version for `VERSION`:

```sh
gh attestation verify oci://ghcr.io/ulef1005/brick-work:VERSION --owner Ulef1005
gh attestation verify oci://ghcr.io/ulef1005/brick-work:VERSION --owner Ulef1005 \
  --predicate-type https://spdx.dev/Document/v2.3
```

The first command checks the build provenance: the image was built by this repository's release workflow from that tag. The second checks the software bill of materials (SBOM, in SPDX) attached to the same image, which lists the packages inside it. Both print the verified attestation; a failure means the image did not come from this repository's release, so do not start it.

## Check the result

1. Open `/api/v2/health` (no token). It shows the app version and the schema, for example `"app": "1.0.0"` and `"schema": "4.2"`. `/api/v1/health` answers the same.
2. Run `brickwork check` (with Docker: `docker compose exec brickwork brickwork check`), or press **Run integrity check** under **Manage → Tools & Admin → Database**. Both must pass.
3. Open **Sets** and compare what you see with your last export if you kept a note of the counts.

## Go back

Stop Brick Work, put the backed-up `brickwork.db` and `secret.key` back, check out the older version's tag, and refresh the image before you start it. For 0.9.0 and older, run `docker compose build`: their `compose.yaml` builds from source. From 1.0.0 on, run `docker compose pull`. Then run `docker compose up -d`. Without that step, Docker starts the newer image again, and it upgrades the restored file once more. Changes made after the upgrade are not in the backup. [Back up and restore](back-up-and-restore.md#restore) has the details.

## What next

- [Back up and restore](back-up-and-restore.md) for the backup itself.
- [Settings and maintenance](settings-and-maintenance.md) for the catalogue and the checks.
