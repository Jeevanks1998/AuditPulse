2. backend/consent/region_detector.py
New file

Create a dedicated region-detection module.

This is important because region detection should not be mixed with consent scoring.

It should determine:

detected region
framework
confidence
detection source
reason

For example:

URL
 ↓
Region Detection
 ↓
Europe
 ↓
GDPR
 ↓
Consent Audit
 ↓
GDPR Result
Detection signals

Use multiple signals instead of relying only on the domain.

Strong signals
.fr
.de
.it
.es
.be
.ch
.uk
.co.uk
.ie
.nl
.se
.no
.dk
.fi
.at
.pt
.pl
.cz
.ro
etc.

Also inspect:

hreflang
<html lang>
country/language selectors
canonical URL
alternate URLs
geographic path
locale path such as /fr/, /de/, /uk/
consent-platform configuration
privacy-policy regional references
Result

The backend should return something similar conceptually to:

Detected Region: France
Framework: GDPR
Confidence: High
Detection Source: Domain + hreflang

or:

Detected Region: California
Framework: CCPA/CPRA
Confidence: Medium
Detection Source: Privacy policy + site signals
