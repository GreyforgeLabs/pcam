from pcam_runtime import PCG32Stream


def test_pcg32_reference_vector_and_snapshot_restore():
    stream = PCG32Stream.seeded(seed=42, stream_selector=54)
    values = []
    for _ in range(5):
        stream, value = stream.draw_u32()
        values.append(value)
    assert values == [0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B]
    restored = PCG32Stream.from_snapshot(stream.to_snapshot())
    assert restored == stream
    assert restored.draw_u32() == stream.draw_u32()
