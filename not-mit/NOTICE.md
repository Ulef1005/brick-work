# Not MIT: Rebrickable and LEGO material

Everything in this folder is **not** under the MIT licence that covers the rest of this repository. It is third-party material that the public demo and the website pictures use.

## Who owns what

| What | In this folder | Owner |
|---|---|---|
| Set, minifigure and part pictures | `rebrickable/images/` | Pictures of LEGO products: the LEGO Group owns the products and, for the catalogue photos, the pictures. Rebrickable hosts them and supplies the part renders. |
| Set, part, colour and minifigure data (names, numbers, years, part lists) | `rebrickable/sets.json` | [Rebrickable](https://rebrickable.com), from its CSV download. |

LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project. Rebrickable is a trademark of its owner.

## Why it is here, and the terms behind it

Rebrickable's terms ([rebrickable.com/terms](https://rebrickable.com/terms), read on 2026-11-13) say that "Images of Sets, Parts and Minifigs may be used on external websites or apps", that LDraw part renders are offered for bulk download on its Downloads page, and that its set and part pictures "are LEGO IP. You may use them, but their usage must adhere to the LEGO copyright rules." The LEGO Fair Play policy adds that the LEGO logo must not appear on an unofficial site, so every picture here was opened and checked for the logo and for box art.

The terms speak of use on websites and apps and do not clearly cover redistribution in a public repository. The owner of this repository decided on 2026-11-13 to keep the material in this one separate, clearly marked folder anyway.

## What you may and may not do

- You may read and run the demo and the website with these files, as this repository does.
- You may **not** treat them as MIT-licensed, reuse them in another project under that licence, or include them in a product or a release package.
- You may **not** use the pictures to train AI models, and you may not download more of them in bulk or by script; Rebrickable's terms forbid both.
- If the owner of any of this material asks for it to be removed, it is removed.

## Where it stays out

The folder is not part of the Python package, not copied into the Docker image (`.dockerignore`), and not part of a release. The site build copies the pictures it needs to the public demo and the website only.

## Credit

Part and set images: Rebrickable. Data: Rebrickable.

## How it was made

`rebrickable/sets.json` is cut from Rebrickable's CSV download by `scripts/extract_rebrickable.py`. Each set picture was fetched once, by hand, from the picture URL named in that download, checked, and resized. Part pictures come from Rebrickable's LDraw render zips on its Downloads page. The collection built around these sets in the demo (copies, storage, prices, orders) is invented.
