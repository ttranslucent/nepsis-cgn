from nepsis.deviance import DevianceMonitor


def test_deviance_monitor_adjusts_tau_when_near_misses_high():
    monitor = DevianceMonitor(sensitivity=0.5, window=20, min_samples=5, near_miss_threshold=0.8)
    manifold_name = "reasoning.seed_voronoi"

    # Record several near misses
    for _ in range(5):
        monitor.record(manifold_name, outcome="REJECTED", blue_score=0.0, drift=True)

    adjusted = monitor.adjust_tau(manifold_name, base_tau=0.2)
    assert adjusted < 0.2


def test_deviance_monitor_leaves_tau_when_history_small():
    monitor = DevianceMonitor(sensitivity=0.5, window=20, min_samples=5, near_miss_threshold=0.8)
    manifold_name = "reasoning.seed_voronoi"
    monitor.record(manifold_name, outcome="SUCCESS", blue_score=1.0, drift=False)
    adjusted = monitor.adjust_tau(manifold_name, base_tau=0.2)
    assert adjusted == 0.2
