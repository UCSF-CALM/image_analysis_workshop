"""Calculate a 3D point spread function (PSF) for deconvolving the BPAE z-stack.

Run it from the top folder of the workshop repository with:

    uv run src/make_airy_psf.py

or, if your copy of the data is somewhere else, give the folder or file:

    uv run src/make_airy_psf.py "D:/my data/BPAE_100x_ZStack_3Crop"

The model: an ideal (aberration-free) objective with NA 1.40 in immersion oil.
In the focal plane this PSF is exactly the Airy disk:

    intensity(r) = [ 2 J1(v) / v ]^2      with v = 2 pi NA r / wavelength

Above and below focus the same model gives the familiar "hourglass" shape.
Think of it as adding up all the light waves that the objective collects
(one for each angle up to the NA), each with its own delay when you move
out of focus.  In focus the waves are all in step and you get the Airy disk.

The pixel size and z-step are read from the data, so the PSF has the same
sampling as the images.  One PSF is made for each channel, because the PSF
size depends on the emission wavelength.  Each PSF is saved as a 32-bit
z-stack (pixel values add up to 1) next to the data, with a picture
(..._PSF.png) showing the PSFs from above (XY) and from the side (XZ).
"""

import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tifffile
from scipy import special

DATA = Path("Z:/ImageAnalysisCourse/ZStack_100x_BPAE/BPAE_100x_ZStack_3Crop/"
            "BPAE_100x_ZStack_3_MMStack_Pos0.ome.tif")

NA = 1.40                   # numerical aperture (Plan Apo VC 100x NA 1.40 Oil)
N_IMMERSION = 1.515         # refractive index of immersion oil

# Center of the emission filter for each channel, in the order of the stack.
EMISSION_NM = {"Cy3": 605, "FITC": 520, "DAPI": 455}

PSF_XY_UM = 4.0             # width and height of the PSF image, in microns
PSF_Z_UM = 8.0              # depth of the PSF stack, in microns


def find_data(argument):
    path = Path(argument) if argument else DATA
    if path.is_dir():
        path = next(path.glob("*.ome.tif"))
    return path


def pixel_sizes(path):
    """Read the pixel size and z-step (both in microns) from the OME metadata."""
    with tifffile.TiffFile(path) as tif:
        ome = tif.ome_metadata
    xy = float(re.search(r'PhysicalSizeX="([\d.eE+-]+)"', ome).group(1))
    z = float(re.search(r'PhysicalSizeZ="([\d.eE+-]+)"', ome).group(1))
    return xy, z


def odd_size(length_um, step_um):
    """Number of pixels covering the length, odd so that there is a center pixel."""
    n = int(round(length_um / step_um))
    return n + 1 if n % 2 == 0 else n


def airy_psf_3d(wavelength_um, xy_um, z_um, nxy, nz):
    """3D PSF of an ideal objective; the plane in focus is the Airy disk."""
    k = 2 * np.pi / wavelength_um
    # Each wave entering the objective at a different angle is described by
    # s = n * sin(angle), which runs from 0 (straight on) up to the NA.
    s = np.linspace(0, NA, 400)
    ds = s[1] - s[0]

    # Distance of every pixel to the center of the image, in microns.
    coords = (np.arange(nxy) - nxy // 2) * xy_um
    r = np.hypot(*np.meshgrid(coords, coords, indexing="ij"))
    # Many pixels have the same distance; only calculate each distance once.
    r_unique, r_index = np.unique(r, return_inverse=True)
    bessel = special.j0(k * np.outer(r_unique, s)) * s   # spread over the ring

    psf = np.empty((nz, nxy, nxy))
    for i, z in enumerate((np.arange(nz) - nz // 2) * z_um):
        # Out of focus, waves at steeper angles get a different delay.
        delay = np.exp(1j * k * z * np.sqrt(N_IMMERSION**2 - s**2))
        field = (bessel * delay).sum(axis=1) * ds
        psf[i] = (np.abs(field) ** 2)[r_index].reshape(r.shape)
    return psf / psf.sum()


data = find_data(sys.argv[1] if len(sys.argv) > 1 else None)
xy_um, z_um = pixel_sizes(data)
nxy, nz = odd_size(PSF_XY_UM, xy_um), odd_size(PSF_Z_UM, z_um)
print(f"Data: {data.name}")
print(f"Pixel size {xy_um} um, z-step {z_um} um -> PSF of {nz} x {nxy} x {nxy} pixels")

fig, axes = plt.subplots(2, len(EMISSION_NM), figsize=(4 * len(EMISSION_NM), 7),
                         height_ratios=[nxy * xy_um, nz * z_um])
for column, (name, emission) in enumerate(EMISSION_NM.items()):
    psf = airy_psf_3d(emission / 1000, xy_um, z_um, nxy, nz)

    output = data.parent / f"PSF_{name}_{emission}nm.tif"
    tifffile.imwrite(output, psf.astype(np.float32), imagej=True,
                     resolution=(1 / xy_um, 1 / xy_um),
                     metadata={"axes": "ZYX", "spacing": z_um, "unit": "micron"})

    # Size of the Airy disk: radius of the first dark ring, 0.61 * wavelength / NA.
    print(f"  {name:5s} {emission} nm: Airy disk radius "
          f"{0.61 * emission / 1000 / NA:.3f} um -> saved {output.name}")

    # Show the PSF from above (focal plane) and from the side (through the center).
    half_xy, half_z = nxy * xy_um / 2, nz * z_um / 2
    axes[0, column].imshow(psf[nz // 2], cmap="magma",
                           extent=[-half_xy, half_xy, -half_xy, half_xy])
    axes[0, column].set_title(f"{name} ({emission} nm): XY in focus")
    # Square root makes the faint parts above and below focus easier to see.
    axes[1, column].imshow(np.sqrt(psf[:, nxy // 2, :]), cmap="magma", aspect="auto",
                           extent=[-half_xy, half_xy, -half_z, half_z])
    axes[1, column].set_title("XZ (square root of intensity)")
    axes[1, column].set_xlabel("x (µm)")
axes[0, 0].set_ylabel("y (µm)")
axes[1, 0].set_ylabel("z (µm)")
fig.tight_layout()
picture = data.parent / "PSF.png"
fig.savefig(picture, dpi=120)
print(f"Saved {picture.name}")
plt.show()
