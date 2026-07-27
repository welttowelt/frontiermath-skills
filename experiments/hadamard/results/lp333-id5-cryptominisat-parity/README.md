# ID5 CryptoMiniSat parity-recovery arm

The frozen one-hour XOR-native arm completed `unknown` with no SAT model.

- positive control: pass;
- target XORs recovered: 83,376;
- XORs supplied to five Gaussian matrices: 82,962 initially;
- Gaussian matrices used: 5;
- maximum observed RSS: 382,025,728 bytes;
- external wall: 3,615.131118 seconds;
- manifest SHA-256:
  `e09c12447280722c3936cc512b1ac76e429d3de645cb127be92bbab758d4ca58`.

The formula, source audit, solver executable and library, Homebrew bottle and
receipt, preregistration, and SAT control bindings passed. XOR/Gauss telemetry
shows that the intended parity intervention fired; reaching the wall ceiling
without a model is nondecisive.
