# Tests of compute_ceiling_floor, compute_value_gap and compute_tiers, cut from tests/test_vor.py (now test_advisor_table.py) when those columns were dropped (archive/python/draft used them).

class TestComputeCeilingFloor:
    RMSE = 50.0

    def _healthy(self, proj=200.0):
        return pd.DataFrame({
            "projected_ppr": [proj],
            "games": [17],
            "games_delta": [0],
        })

    def _injured(self, proj=200.0, games=8, delta=-9):
        return pd.DataFrame({
            "projected_ppr": [proj],
            "games": [games],
            "games_delta": [delta],
        })

    def test_healthy_player_ceiling_equals_proj_plus_rmse(self):
        result = compute_ceiling_floor(self._healthy(200.0), self.RMSE)
        assert result["ceiling"].iloc[0] == pytest.approx(250.0)

    def test_healthy_player_floor_equals_proj_minus_rmse(self):
        result = compute_ceiling_floor(self._healthy(200.0), self.RMSE)
        assert result["floor"].iloc[0] == pytest.approx(150.0)

    def test_floor_clipped_at_zero(self):
        result = compute_ceiling_floor(self._healthy(30.0), self.RMSE)
        assert result["floor"].iloc[0] == pytest.approx(0.0)

    def test_healthy_availability_flag_false(self):
        result = compute_ceiling_floor(self._healthy(), self.RMSE)
        assert not result["availability_flag"].iloc[0]

    def test_injured_availability_flag_true(self):
        result = compute_ceiling_floor(self._injured(), self.RMSE)
        assert result["availability_flag"].iloc[0]

    def test_injured_ceiling_at_least_rmse_ceiling(self):
        proj = 100.0
        result = compute_ceiling_floor(self._injured(proj=proj, games=8, delta=-9), self.RMSE)
        rmse_ceiling = proj + self.RMSE
        assert result["ceiling"].iloc[0] >= rmse_ceiling



class TestComputeTiers:
    def test_eight_tiers_assigned(self):
        df = pd.DataFrame({"vor": [float(i) for i in range(16)]})
        result = compute_tiers(df)
        assert set(result["tier"].dropna().astype(int).unique()) == set(range(1, 9))

    def test_highest_vor_gets_tier_one(self):
        df = pd.DataFrame({"vor": [float(i) for i in range(16)]})
        result = compute_tiers(df)
        best_tier = result.loc[result["vor"].idxmax(), "tier"]
        assert int(best_tier) == 1

class TestComputeValueGap:
    def test_value_gap_equals_adp_minus_vor_rank(self):
        df = pd.DataFrame({
            "vor":     [100.0, 50.0, 0.0],
            "adp":      [1.0,   3.0,  5.0],
        })
        result = compute_value_gap(df)
        expected = result["adp"] - result["vor_rank"]
        pd.testing.assert_series_equal(result["value_gap"], expected, check_names=False)

    def test_sorted_descending_by_vor(self):
        df = pd.DataFrame({
            "vor":     [0.0, 100.0, 50.0],
            "adp":      [5.0,  1.0,   3.0],
        })
        result = compute_value_gap(df)
        assert result["vor"].is_monotonic_decreasing


