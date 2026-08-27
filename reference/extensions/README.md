# Reference Host Extension Modules

These files are inert module contracts, not portable definition code. A host registration may bind one contract to a runtime hook only when the SHA-256 of the exact source bytes matches the registration's `implementation_hash`.

The reference loader accepts only hooks compiled into the runtime. It does not import Python modules, execute definition payloads, resolve network locations, or discover code by namespace. Unknown hooks and authoritative registrations without verified source bytes fail closed.

`tick-counter-v1.json` defines the bounded conformance pilot. At tick start, after event delivery, profile declarations execute in namespace order. Active action declarations then execute in action-instance order and namespace order. Each declaration performs a checked U64 addition of payload field `increment` into `simulation.extension_state.<namespace>.counter`.
