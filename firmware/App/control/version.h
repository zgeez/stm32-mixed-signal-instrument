#ifndef VERSION_H
#define VERSION_H

/* What the device tells a host about itself.
 *
 * The version is bumped by hand when host-visible behaviour changes, so the application
 * can tell whether it is talking to a build it understands. The build id is injected by
 * CMake from the working tree: without it a measurement cannot be tied to the image that
 * produced it, which is the one thing a name and a protocol number cannot establish.
 */

/* Kept in step with the desktop package, because the two ship as one release. A test
 * compares this against desktop/pyproject.toml so they cannot drift apart unnoticed. */
#define FIRMWARE_VERSION_MAJOR 0U
#define FIRMWARE_VERSION_MINOR 1U
#define FIRMWARE_VERSION_PATCH 0U

/* Longest identity the reply carries; a short commit hash fits with room to spare. */
#define FIRMWARE_BUILD_ID_MAX 16U

#ifndef FIRMWARE_BUILD_ID
#define FIRMWARE_BUILD_ID "unknown"
#endif

#endif
