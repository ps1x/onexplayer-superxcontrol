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

Add a dedicated `oxp_superx` board id and route it through the same handling as
`oxp_x1` for now.

This keeps Super X identity explicit while allowing future Super X-specific
quirks if the hardware diverges.

## Maintainers

From mainline `MAINTAINERS`:

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
git commit -s -m "platform/x86: oxpec: add support for OneXPlayer Super X"
./scripts/get_maintainer.pl -f drivers/platform/x86/oxpec.c
```

Then send with `git send-email` to the maintainers and `platform-driver-x86`.
