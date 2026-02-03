# DNS Tool Report

## Implementation Details
The DNS Tool is a Go application using the standard `net` and `net/http` packages. It provides a `/lookup` endpoint to query DNS records.

## Supported Record Types
- A (IPv4)
- AAAA (IPv6)
- MX
- TXT
- CNAME

## Limitations
### TTL
The Go standard library `net` package does not expose the TTL (Time To Live) of DNS records in its lookup functions (`LookupIP`, `LookupMX`, etc.).
The requirements specified a response field `"ttl": 300`.
**Current Behavior:** The application currently returns a hardcoded placeholder TTL of `300` for all successful responses to satisfy the schema requirement.
**Suggestion:** If accurate TTLs are required, the application should be migrated to use a more robust DNS library such as `github.com/miekg/dns`, which provides full access to DNS message details including TTL.

## Friction Points
- **Standard Library Limitations:** As noted above, the lack of TTL support in `net` package was a minor friction point requiring a workaround (dummy value).

## Feature Suggestions
- **Reverse Lookup:** Add support for reverse DNS lookups (IP to hostname).
- **Custom Nameservers:** Allow the user to specify a custom nameserver (e.g., `8.8.8.8`) for the lookup instead of using the system resolver.
- **Detailed Errors:** Provide more specific error codes (e.g., NXDOMAIN, SERVFAIL).
