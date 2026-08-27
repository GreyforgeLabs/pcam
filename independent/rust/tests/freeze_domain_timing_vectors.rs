use pcam_independent::freezes::{FreezeToken, end_tick, is_frozen};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

#[test]
fn independent_all_core_freeze_domains_share_exact_timing_and_target_scope() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let vector: Value = serde_json::from_slice(
        &fs::read(root.join("tests/vectors/freeze-domain-timing.json")).unwrap(),
    )
    .unwrap();
    let token: FreezeToken = serde_json::from_value(vector["token"].clone()).unwrap();
    let mut tokens = vec![token];
    for expected in vector["expected"].as_array().unwrap() {
        let tick = expected["tick"].as_u64().unwrap();
        for domain in vector["domains"].as_array().unwrap() {
            let domain = domain.as_str().unwrap();
            assert_eq!(
                is_frozen(&tokens, tick, 7, domain),
                expected["target_frozen"].as_bool().unwrap()
            );
            assert_eq!(
                is_frozen(&tokens, tick, 8, domain),
                expected["other_target_frozen"].as_bool().unwrap()
            );
        }
        tokens = end_tick(&tokens, tick).unwrap();
        assert_eq!(
            tokens.first().map(|token| token.remaining_ticks),
            expected["remaining_after_tick"].as_u64()
        );
    }
}
