# LanguageTool / Temurin candidate distribution

This directory records evidence, not approval to redistribute every component.
The release validator currently rejects the candidate: dictionary terms,
corresponding source and complete third-party notice coverage remain unresolved.
Do not remove that gate based on the main LGPL/GPL-with-Classpath licenses alone.

`LanguageTool-LGPL-2.1.txt` is the exact COPYING.txt from the SHA-256-pinned
LanguageTool 6.6 ZIP. `Eclipse-Temurin-GPL2-Classpath.txt` preserves the JDK
license/additional information/notices, and `Eclipse-Temurin-NOTICE.txt` preserves
the exact upstream NOTICE. jlink's entire `runtime/legal/` tree must also ship.
The complete original `languagetool/third-party-licenses/` tree and embedded JAR
notices are preserved. The upstream third-party README contains older versions;
it cannot determine the licenses of all actual 6.6 ZIP dependencies.

`LanguageTool-6.6-evidence.json` inventories all 141 candidate JARs, 110 dictionary
files (including entries inside JARs), the embedded POMs/notices/manifests and
runtime legal notices and native files embedded inside JARs. It includes the exact fetched POM URLs, content hashes,
declarations and 42 binary identity checks against Maven Central. These checks
match SHA-256 of the distributed JAR to the upstream JAR before using its POM.
POM declarations for shaded dependencies remain attached to that dependency.
Native payloads (for example Hunspell, JNA and shaded Netty libraries) require
their own redistribution/source review; a wrapper's POM does not settle that.
Multiple license declarations are preserved without inventing AND/OR choices.

Examples requiring separate treatment include Asturian dictionary GPL v3,
Irish dictionary GPL v2, Catalan dictionary GPL/LGPL declarations, and the
embedded MyBatis/JAXB dependencies. This evidence is not a claim that every
dictionary uses LGPL, or that a POM's source-code license covers its data.

`preparar_languagetool.py runtime` generates `license-audit.json` and a CycloneDX
inventory, exporting embedded POMs and notices byte for byte into
`LICENSES/embedded/`. `smoke` may inspect this local prototype, while `validate`,
PyInstaller and delivery scripts reject an unresolved release audit.

Release approval is a separate, repository-owned decision in
`recursos/languagetool-release-approval.json`, currently **blocked**. The tool
never generates approval. Clearing an inventory's `unresolved` list or rewriting
its checksums does not authorize release. The primary evidence's status must
also be approved, and the shipped decision must exactly match the repository.

A future reviewed decision must bind the complete candidate inventory hash and
cover every JAR, shaded POM, dictionary, native payload and runtime/resource
aggregate. Each component needs an explicit reviewed license expression with
hashed evidence files, a reviewed HTTPS source URL/archive hash with evidence
of availability, and reviewed notice files with matching hashes. Reviewer/date
attribution and exact coverage are required. These are review records, not
legal conclusions inferred from package names. Synthetic approvals exist only
in isolated tests; no real component is approved here.

Ordinary push/PR CI performs verification and publishes no executable. The
self-contained release job requires an explicit workflow_dispatch input and
still runs all approval/resource gates. Direct Inno compilation invokes the
same validator from the repository build environment; existence-only guards or
a stale marker cannot authorize a candidate.

Primary sources:

- [LanguageTool 6.6 announcement and ZIP checksum](https://forum.languagetool.org/t/ann-languagetool-6-6/11206)
- [LanguageTool 6.6 source and licensing notice](https://github.com/languagetool-org/languagetool/tree/v6.6)
- [Temurin 17.0.20.1+1 release](https://github.com/adoptium/temurin17-binaries/releases/tag/jdk-17.0.20.1%2B1)
- [Portuguese dictionary source](https://github.com/languagetool-org/portuguese-pos-dict)
- [Maven Central](https://repo.maven.apache.org/maven2/) — exact versioned artifact/POM links and hashes are in the evidence JSON.

Remaining release work: map each dictionary to its actual terms and complete
corresponding source distribution, settle inherited/missing declarations using
the linked evidence, verify complete license/NOTICE texts, validate the final
SBOM, then build and smoke the portable/installer artifacts. No release approval
or source offer is created by this inventory.
