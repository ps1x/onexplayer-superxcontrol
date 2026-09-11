# OneXPlayer Super X camera rotation

The internal Chicony camera (`04f2:b7a3`) delivers pixels in its native,
upside-down mounting orientation. The Super X ACPI tables describe the colour
camera as `PRT1.CAM1`; its `_PLD.Rotation` field is `4`, meaning 180 degrees.
Windows associates the UVC interface with this ACPI child and uses the generic
Microsoft `usbvideo.sys` driver.

Linux currently associates the interface with the parent `PRT1` firmware node,
so libcamera receives no mounting rotation. The adjacent libcamera patch adds a
narrow DMI + USB-ID quirk, publishes the standard `Rotation=180` camera
property, and sets the native stream orientation to `Rotate180`. PipeWire then
exports `SPA_META_VideoTransform` to normal camera clients. This is metadata on
the real camera node; it does not create a virtual camera.

The quirk matches only:

- DMI vendor `ONE-NETBOOK`
- DMI product `ONEXPLAYER SUPER X`
- USB camera `04f2:b7a3`

Rebuild the distribution's libcamera package with
`0001-libcamera-uvc-superx-rotation.patch` applied. Install
`51-superx-camera.conf` as
`~/.config/wireplumber/wireplumber.conf.d/51-superx-camera.conf`. That rule
disables only the duplicate colour-camera V4L2 device, allowing WirePlumber's
built-in arbitration to publish the physical libcamera node instead. Restart
WirePlumber after installing both pieces.

On the live Super X, the resulting node reports `device.api=libcamera` and
`api.libcamera.rotation=180`.

Chrome uses its direct V4L2 backend by default, which bypasses that physical
libcamera node and loses the rotation. Enable Chrome's built-in PipeWire camera
backend with:

```text
--enable-features=WebRtcPipeWireCamera
```

For the local GNOME launcher, add that argument to each `Exec=` line in
`~/.local/share/applications/google-chrome.desktop`, then fully restart Chrome.
This remains the physical camera path: Chrome connects to the PipeWire node
backed by libcamera, while WirePlumber owns `/dev/video0`. No v4l2loopback or
other virtual camera is involved.

`chrome-camera-test.html` requests the real browser camera, draws a frame to an
untransformed canvas, and marks the page `CAMERA_TEST_READY`. A successful raw
PNG from that canvas should have undefined EXIF orientation and upright pixels;
this distinguishes a real frame transform from an orientation-aware image
viewer hiding upside-down pixel data.
