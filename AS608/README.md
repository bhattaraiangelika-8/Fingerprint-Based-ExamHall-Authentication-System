# Fingerprint Module Library

This is a Python library for interacting with fingerprint modules backed by the AS608 Synochip processor. This includes the following fingerprint modules:

* AS608
* R307
* ZFM-20
* FPM10A
* GT-511C3
* JM-101

# Install

```
pip install git+https://github.com/omaraflak/as608.git
```

To enroll a fingerprint:

```python
from fingerprint import (
    FingerprintModule,
    CaptureFingerImage,
    ExtractFeatures,
    GenerateTemplate,
    StoreTemplate,
    get_port_from_user,
    BUFFER_1,
    BUFFER_2
)

port = get_port_from_user()
module = FingerprintModule(port)

if not module.connect():
    print("Could not connect.")
    exit(1)

input("Press enter to scan finger.")
result = module.capture_finger_image()
if result != CaptureFingerImage.SUCCESS:
    print("Could not capture finger image.")
    exit(1)

print("Extracting fingerprint features...")
result = module.extract_features(BUFFER_1)
if result != ExtractFeatures.SUCCESS:
    print("Could not extract fingerprint features.")
    exit(1)

input("Press enter to scan finger.")
result = module.capture_finger_image()
if result != CaptureFingerImage.SUCCESS:
    print("Could not capture finger image.")
    exit(1)

print("Extracting fingerprint features...")
result = module.extract_features(BUFFER_2)
if result != ExtractFeatures.SUCCESS:
    print("Could not extract fingerprint features.")
    exit(1)

print("Generating fingerprint template...")
result = module.generate_template()
if result != GenerateTemplate.SUCCESS:
    print("Could not generate fingerprint template.")
    exit(1)

print("Getting next available page id...")
page_id = module.get_next_page_id()
if page_id is None:
    print("Could not get next available page id.")
    exit(1)

print(f"Saving fingerprint template in page {page_id}...")
result = module.store_template(page_id, BUFFER_1)
if result != StoreTemplate.SUCCESS:
    print("Could not save fingerprint template.")
    exit(1)

print("Done!")
module.disconnect()
```

To verify if a fingerprint is in the module:

```python
from fingerprint import (
    FingerprintModule,
    CaptureFingerImage,
    ExtractFeatures,
    get_port_from_user,
    BUFFER_1
)

port = get_port_from_user()
module = FingerprintModule(port)

if not module.connect():
    print("Could not connect.")
    exit(1)

input("Press enter to scan finger.")
result = module.capture_finger_image()
if result != CaptureFingerImage.SUCCESS:
    print("Could not capture finger image.")
    exit(1)

print("Extracting fingerprint features...")
result = module.extract_features(BUFFER_1)
if result != ExtractFeatures.SUCCESS:
    print("Could not extract fingerprint features.")
    exit(1)

print("Searching fingerprint...")
result = module.search_template(BUFFER_1, page_id=0, template_count=256)
if result.found_match:
    print(f"Found matching template at {result.page_id} with score {result.matching_score}")
else:
    print("Did not find any match!")

module.disconnect()
```

To get an image of your fingerprint:

```python
from fingerprint import FingerprintModule, CaptureFingerImage, get_port_from_user
import matplotlib.pyplot as plt

port = get_port_from_user()
module = FingerprintModule(port)

if not module.connect():
    print("Could not connect.")
    exit(1)

input("Press enter to scan finger.")
result = module.capture_finger_image()
if result != CaptureFingerImage.SUCCESS:
    print("Could not capture finger image.")
    exit(1)

print("Transfering bytes...")
data = module.read_image_buffer()
if not data:
    print("Could not read image buffer.")
    exit(1)

module.disconnect()

image = FingerprintModule.decode_image_buffer(data)
plt.imshow(image, cmap='grey')
plt.show()
```

For a full list of commands, explore the library!

# Module Overview

This library exposes the barebone commands provided by the module. This means you need a little background on how the module actually works to understand the library.

### Vocabulary

* **Feature**: A feature is a set of intermediate data extracted from a raw fingerprint image. This data is not persisted.
* **Template**: A template is a finalized, compressed version of the fingerprint features, ready for storage and matching. This is what is actually stored in the module after enrolling a fingerprint.

### Enrolling

At a high level, registering a new fingerprint in the module is done like this:

1) Scan the finger a first time to get an image
2) Extract the *features* of the fingerprint image
3) Repeat 1 & 2 a second time with the same finger
4) Combine both feature sets into a single *template*
5) Store the template in the persistent memory

### Matching

At a high level, checking if a given fingerprint matches one already registered in the module is done like this:

1) Scan the finger to match
2) Extract the *features* of the fingerprint image
3) Compare the *features* extracted with one or more *templates* from the library

### Non-Persistent Memory (RAM)

The module has **3** different temporary memory locations (memory that is not persisted when the module shuts down).

* **Image Buffer**
  * This location is dedicated to storing the image of the finger placed on the module during the capture. Typically, when using `capture_finger_image`, the image will be stored in this buffer. You can then read this image using `read_image_buffer`. The image is in grey scale and of dimension `288x256`. However, when read, the module will return only the 4 upper bits of each pixel. Which means 1 byte for 2 pixels. That is `288*256/2=36864` bytes are returned, which correspond to all pixels of the image flattened by row.
* **Buffer 1** & **Buffer 2**
  * These locations are meant to hold a fingerprint "features" or "template" (depending on which step of the capture you're in). When you call `extract_features(buffer_id)`, the module will extract the features from the image buffer and write them to the provided buffer (`BUFFER_1` or `BUFFER_2`). When you call `generate_template`, the module will combine the content of `BUFFER_1` and `BUFFER_2` into a fingerprint template, and store it back into both `BUFFER_1` and `BUFFER_2`.

### Persistent Memory (Flash)

The module has **2** different flash memory locations (memory that is persisted when the module shuts down).

* **Template Library**
  * This memory holds the templates of the fingerprints. It can only be accessed via indices, where an index represents a certain template. Those indices are called `page_id`. The number of templates that a module can hold varies by model; you can get that number using `read_system_parameters`.
* **Notepad**
  * This memory is for arbitrary user notes. It is 512 bytes long, split in 16 pages, each 32 bytes. Each page can be read/written in whole — i.e. if you write content less than 32 bytes on one page, the whole 32 bytes of the page are overwritten regardless.
