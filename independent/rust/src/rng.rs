use serde::{Deserialize, Serialize};

pub const PCG32_MULTIPLIER: u64 = 6_364_136_223_846_793_005;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RngError {
    DrawCountOverflow,
    ProfileMismatch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Pcg32Stream {
    pub algorithm_id: String,
    pub draw_count: u64,
    pub state: u64,
    pub stream_selector: u64,
}

impl Pcg32Stream {
    pub fn seeded(seed: u64, stream_selector: u64) -> Self {
        let mut stream = Self {
            algorithm_id: "pcam.pcg32.v1".to_owned(),
            draw_count: 0,
            state: 0,
            stream_selector,
        };
        stream.advance(false).expect("seeding does not count draws");
        stream.state = stream.state.wrapping_add(seed);
        stream.advance(false).expect("seeding does not count draws");
        stream
    }

    pub fn increment(&self) -> u64 {
        self.stream_selector.wrapping_shl(1) | 1
    }

    pub fn draw_u32(&mut self) -> Result<u32, RngError> {
        self.advance(true)
    }

    pub fn from_snapshot(snapshot: Self) -> Result<Self, RngError> {
        if snapshot.algorithm_id != "pcam.pcg32.v1" {
            return Err(RngError::ProfileMismatch);
        }
        Ok(snapshot)
    }

    fn advance(&mut self, count_draw: bool) -> Result<u32, RngError> {
        let old_state = self.state;
        let next_draw_count = if count_draw {
            self.draw_count
                .checked_add(1)
                .ok_or(RngError::DrawCountOverflow)?
        } else {
            self.draw_count
        };
        self.state = old_state
            .wrapping_mul(PCG32_MULTIPLIER)
            .wrapping_add(self.increment());
        let xor_shifted = (((old_state >> 18) ^ old_state) >> 27) as u32;
        let rotation = (old_state >> 59) as u32;
        if count_draw {
            self.draw_count = next_draw_count;
        }
        Ok(xor_shifted.rotate_right(rotation))
    }
}
