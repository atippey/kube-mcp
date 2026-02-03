# Time Tool Report

## Implementation Details
The time-tool is a Go application using `net/http` to provide time in various timezones and formats.
It uses `alpine` base image with `tzdata` installed to support timezone loading.

## Verification
- Validated Go application functionality locally using `curl`.
- Confirmed support for RFC3339, Unix timestamp, and Human-readable formats.
- Confirmed timezone conversions (e.g., America/New_York, Europe/Paris).

## Bugs Encountered
- **Docker Rate Limiting**: Encountered `toomanyrequests` from Docker Hub when attempting to build the image in the development environment. This prevented full verification of the Dockerfile build process, although the Go binary built successfully locally.

## Friction Points
- **Timezone Database**: Go's `time.LoadLocation` requires the timezone database to be present on the system. This adds a dependency on `tzdata` package in the Docker image (Alpine). Without it, it would panic or error on non-UTC timezones. This was anticipated and handled in the Dockerfile.

## Feature Suggestions
- **Custom Format Strings**: Currently supports fixed formats ("rfc3339", "unix", "human"). Adding support for Go layout strings or strftime-like patterns could provide more flexibility.
- **Current Location Detection**: Could potentially use IP geolocation to default to the caller's timezone if not specified (though this adds complexity and external dependencies).
