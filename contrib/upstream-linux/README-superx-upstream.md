# OneXPlayer Super X upstream patch notes

## What is wrong today

On the tested OneXPlayer Super X system the in-tree `oxpec` driver is present,
but it does not auto-load because mainline `drivers/platform/x86/oxpec.c` does
not currently match this DMI string:

- board vendor: `ONE-NETBOOK`
- board name: `ONEXPLAYER SUPER X`
- product name: `ONEXPLAYER SUPER X`

The local machine reports:

```text
dmi:bvnAmericanMegatrendsInternational,LLC.:...:svnONE-NETBOOK:pnONEXPLAYERSUPERX:...:rvnONE-NETBOOK:rnONEXPLAYERSUPERX:...
```

## Why this matters

Without a matching DMI entry, the built-in Fedora `oxpec` module is not
autoloaded, so the fan hwmon node is not created by the in-tree driver.

## Proposed approach

Add a DMI entry for OneXPlayer Super X and route it through the existing
`oxp_g1_a` board data.

This matches the v3 review direction and keeps the upstream patch limited to a
single DMI-table addition.

## Maintainers

From mainline `MAINTAINERS`:

- Ilpo Järvinen `<ilpo.jarvinen@linux.intel.com>`
- Antheas Kapenekakis `<lkml@antheas.dev>`
- Derek John Clark `<derekjohn.clark@gmail.com>`
- Joaquín Ignacio Aramendía `<samsagax@gmail.com>`
- `platform-driver-x86@vger.kernel.org`

## Suggested send-email flow

From a Linux kernel git checkout:

```bash
git checkout -b oxpec-superx
cp /path/to/this/repo/contrib/upstream-linux/oxpec.superx.patch .
git apply oxpec.superx.patch

git add drivers/platform/x86/oxpec.c
git -c user.name="Alexander Egorov" \
  -c user.email="begeebe@gmail.com" \
  commit -s -F /path/to/this/repo/contrib/upstream-linux/commit-message-superx.txt \
  --author="Alexander Egorov <begeebe@gmail.com>"
./scripts/get_maintainer.pl -f drivers/platform/x86/oxpec.c
```

Generate and inspect the patch:

```bash
git format-patch -v3 -1 \
  --from="Alexander Egorov <begeebe@gmail.com>" \
  --subject-prefix="PATCH" \
  --output-directory /tmp/oxpec-superx-v3
```

Then send with `git send-email` to the maintainers and `platform-driver-x86`:

```bash
git send-email --confirm=never /tmp/oxpec-superx-v3/*.patch \
  --to="platform-driver-x86@vger.kernel.org" \
  --cc="ilpo.jarvinen@linux.intel.com" \
  --cc="lkml@antheas.dev" \
  --cc="derekjohn.clark@gmail.com" \
  --cc="samsagax@gmail.com" \
  --in-reply-to="20260330101028.876277-1-begeebe@gmail.com"
```

The local `git send-email` SMTP config is already pointed at
`begeebe@gmail.com`, but it still needs a Gmail app password in the git
credential store before the final send can complete.
