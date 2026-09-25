import pytest

from iOpenPod.GUI.synesthesia.persistent_world import (
    ConflictingFieldImpulseError,
    ExperienceTimeRegressionError,
    FieldAdvance,
    FieldForcing,
    FieldGenesis,
    FieldImpulse,
    FieldImpulseCharacter,
    FieldWorld,
    InvalidFieldAdvanceError,
    PersistentWorld,
    TransportState,
    UnclassifiedTransportJumpError,
    Vec3,
    WorldAdvance,
    WorldConditions,
    WorldFrame,
    WorldGenesis,
)


def _request(
    experience_time: float,
    musical_time: float,
    *,
    state: TransportState = TransportState.PLAYING,
    epoch: int = 0,
    forcing: FieldForcing | None = None,
) -> FieldAdvance:
    return FieldAdvance(
        experience_time=experience_time,
        musical_time=musical_time,
        transport_state=state,
        transport_epoch=epoch,
        forcing=forcing,
    )


def _impulse(
    identity: str,
    *,
    epoch: int = 0,
    amplitude: float = 0.8,
    character: FieldImpulseCharacter = FieldImpulseCharacter.BURST,
) -> FieldImpulse:
    return FieldImpulse(
        impulse_id=identity,
        musical_event_id=f"music-{identity}",
        transport_epoch=epoch,
        origin=Vec3(0.2, -0.1, 0.3),
        amplitude=amplitude,
        character=character,
        speed=1.25,
        decay_seconds=3.0,
    )


def test_seed_creates_three_deterministic_stable_force_poles_without_topology() -> None:
    first = FieldWorld.create(FieldGenesis(experience_seed=41)).advance(
        _request(0.0, 0.0, state=TransportState.PAUSED)
    )
    again = FieldWorld.create(FieldGenesis(experience_seed=41)).advance(
        _request(0.0, 0.0, state=TransportState.PAUSED)
    )
    other = FieldWorld.create(FieldGenesis(experience_seed=42)).advance(
        _request(0.0, 0.0, state=TransportState.PAUSED)
    )

    assert first == again
    assert tuple(pole.pole_id for pole in first.poles) == (
        "pole.mass",
        "pole.order",
        "pole.excitation",
    )
    assert tuple(pole.position for pole in first.poles) != tuple(
        pole.position for pole in other.poles
    )
    assert not hasattr(first, "nodes")
    assert not hasattr(first, "branches")
    assert not hasattr(first, "camera")
    assert first.forcing.poles == first.poles


def test_impact_is_delivered_once_then_remains_as_an_aging_wave_and_biography() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=9))
    impact = _impulse("impact-1")
    born = world.advance(_request(0.0, 0.0, forcing=FieldForcing(impulses=(impact,))))

    assert born.new_impulses == (impact,)
    assert born.impulses == (impact,)
    assert born.forcing.impulse_intensity == pytest.approx(0.8)
    assert born.total_cause_count == 1
    assert born.scar == born.cause_records[0]

    later = world.advance(_request(1.0, 1.0))

    assert later.new_impulses == ()
    assert len(later.impulses) == 1
    assert later.impulses[0].age_seconds == pytest.approx(1.0)
    assert later.impulses[0].radius == pytest.approx(1.25)
    assert later.impulses[0].strength < impact.strength
    assert later.cause_records == born.cause_records


def test_event_character_survives_while_an_impulse_ages() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=91))
    laser = _impulse("downbeat", character=FieldImpulseCharacter.LASER)
    born = world.advance(_request(0.0, 0.0, forcing=FieldForcing(impulses=(laser,))))
    later = world.advance(_request(0.5, 0.5))

    assert born.impulses[0].character is FieldImpulseCharacter.LASER
    assert later.impulses[0].character is FieldImpulseCharacter.LASER


def test_repeated_cause_is_idempotent_and_changed_content_is_rejected() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=10))
    impact = _impulse("same")
    first = world.advance(_request(0.0, 0.0, forcing=FieldForcing(impulses=(impact,))))
    repeated = world.advance(
        _request(0.2, 0.2, forcing=FieldForcing(impulses=(impact,)))
    )

    assert first.total_cause_count == repeated.total_cause_count == 1
    assert repeated.new_impulses == ()
    assert repeated.cause_records == first.cause_records

    conflicting = _impulse("same", amplitude=0.4)
    with pytest.raises(ConflictingFieldImpulseError, match="changed content"):
        world.advance(
            _request(
                0.3,
                0.3,
                forcing=FieldForcing(impulses=(conflicting,)),
            )
        )


def test_pause_freezes_field_time_forcing_waves_poles_and_revision() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=11))
    live_forcing = FieldForcing(
        activity=0.9,
        low_frequency_mass=0.8,
        fine_excitation=0.7,
        harmonic_coherence=0.6,
        impulses=(_impulse("freeze"),),
    )
    world.advance(_request(0.0, 0.0, forcing=live_forcing))
    moving = world.advance(
        _request(1.0, 1.0, forcing=live_forcing.without_world_state())
    )
    paused = world.advance(
        _request(
            10.0,
            1.0,
            state=TransportState.PAUSED,
            forcing=FieldForcing(
                activity=0.0,
                low_frequency_mass=0.0,
                fine_excitation=0.0,
                harmonic_coherence=0.0,
            ),
        )
    )
    observed_again = world.advance(_request(30.0, 1.0, state=TransportState.PAUSED))

    assert paused.field_time == moving.field_time
    assert paused.delta_seconds == 0.0
    assert paused.forcing.without_world_state() == moving.forcing.without_world_state()
    assert paused.poles == moving.poles
    assert paused.impulses == moving.impulses
    assert paused.cause_records == moving.cause_records
    assert observed_again is paused

    resumed = world.advance(_request(40.0, 1.0))
    progressed = world.advance(_request(40.5, 1.5))
    assert resumed.field_time == paused.field_time
    assert progressed.field_time == pytest.approx(paused.field_time + 0.5)


def test_seek_reanchors_without_backlog_or_rewinding_live_field_state() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=12))
    impact = _impulse("before-seek")
    world.advance(_request(0.0, 0.0, forcing=FieldForcing(impulses=(impact,))))
    before_seek = world.advance(_request(2.0, 2.0))

    sought = world.advance(_request(20.0, 0.5, epoch=1))

    assert sought.transport_epoch == 1
    assert sought.musical_time == 0.5
    assert sought.field_time == before_seek.field_time
    assert sought.delta_seconds == 0.0
    assert sought.impulses == before_seek.impulses
    assert sought.cause_records == before_seek.cause_records
    assert sought.new_impulses == ()


def test_active_waves_and_cause_biography_remain_bounded() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=13))
    frame: WorldFrame | None = None
    for index in range(270):
        seconds = index / 100.0
        impact = FieldImpulse(
            impulse_id=f"impact-{index}",
            musical_event_id=f"music-{index}",
            transport_epoch=0,
            origin=Vec3(0.0, 0.0, 0.0),
            amplitude=1.0,
            speed=1.0,
            decay_seconds=1_000.0,
        )
        frame = world.advance(
            _request(
                seconds,
                seconds,
                forcing=FieldForcing(impulses=(impact,)),
            )
        )

    assert frame is not None
    assert len(frame.impulses) == 8
    assert len(frame.cause_records) == 256
    assert frame.total_cause_count == 270
    assert frame.cause_records[0].record_id == 15
    assert frame.diagnostics == ("field-biography-compacted",)


def test_transport_errors_require_an_explicit_epoch_boundary() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=14))
    world.advance(_request(1.0, 1.0))

    with pytest.raises(ExperienceTimeRegressionError):
        world.advance(_request(0.5, 1.1))
    with pytest.raises(UnclassifiedTransportJumpError, match="Backward musical"):
        world.advance(_request(2.0, 0.5))

    world.advance(_request(2.0, 1.0, state=TransportState.PAUSED))
    with pytest.raises(UnclassifiedTransportJumpError, match="Paused musical"):
        world.advance(_request(3.0, 1.1, state=TransportState.PAUSED))

    world.advance(_request(3.0, 1.0, state=TransportState.ENDED))
    with pytest.raises(UnclassifiedTransportJumpError, match="Restart after end"):
        world.advance(_request(4.0, 1.0))
    assert world.advance(_request(4.0, 0.0, epoch=1))


def test_paused_or_mismatched_epoch_impulses_are_rejected() -> None:
    world = FieldWorld.create(FieldGenesis(experience_seed=15))
    with pytest.raises(InvalidFieldAdvanceError, match="Paused or ended"):
        world.advance(
            _request(
                0.0,
                0.0,
                state=TransportState.PAUSED,
                forcing=FieldForcing(impulses=(_impulse("paused"),)),
            )
        )
    with pytest.raises(InvalidFieldAdvanceError, match="epoch must match"):
        world.advance(
            _request(
                0.0,
                0.0,
                epoch=1,
                forcing=FieldForcing(impulses=(_impulse("wrong-epoch"),)),
            )
        )


def test_transitional_names_are_aliases_not_a_second_world_model() -> None:
    assert PersistentWorld is FieldWorld
    assert WorldAdvance is FieldAdvance
    assert WorldConditions is FieldForcing
    assert WorldGenesis is FieldGenesis
    assert WorldFrame.__name__ == "FieldFrame"

    forcing = FieldForcing(activity=0.4)
    request = WorldAdvance(
        0.0,
        0.0,
        TransportState.PAUSED,
        0,
        conditions=forcing,
    )
    assert request.conditions == forcing
