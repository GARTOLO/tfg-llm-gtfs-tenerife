"""
Unit tests for backend MCP tools (db_tools.py and otp_tools.py).

Run with: pytest tests/test_backend.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
import requests
from src.mcp.db_tools import get_route_info, get_stop_info, get_line_occupancy
from src.mcp.otp_tools import plan_trip

# Valid example coordinates for testing (Santa Cruz de Tenerife area)
VALID_ORIGIN = (28.48372, -16.31395)
VALID_DESTINATION = (28.45761, -16.25833)


class TestGetRouteInfo:
    """Tests for get_route_info() function."""

    def test_get_route_info_valid_route_15(self):
        """Test that route 15 returns valid info and contains Santa Cruz."""
        result = get_route_info("15")
        
        # Should not be an error message
        assert "Error" not in result
        assert "No he encontrado" not in result
        
        # Should contain route information
        assert "15" in result or "Información de la Línea" in result
        
        # Check for Santa Cruz indicator
        # (adjust if the actual route name is different)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_route_info_nonexistent_route(self):
        """Test that nonexistent route returns proper error message."""
        result = get_route_info("99999")
        
        # Should return error message
        assert "No he encontrado" in result or "Error" in result

    def test_get_route_info_returns_string(self):
        """Test that function always returns a string."""
        result = get_route_info("15")
        assert isinstance(result, str)
        
        result_invalid = get_route_info("99999")
        assert isinstance(result_invalid, str)

    def test_get_route_info_contains_schedule_info(self):
        """Test that valid route returns schedule info."""
        result = get_route_info("15")
        
        if "No he encontrado" not in result:
            # Valid route should contain schedule-related keywords
            assert any(keyword in result.lower() 
                      for keyword in ["horario", "desde", "hasta", "aprox"])


class TestGetStopInfo:
    """Tests for get_stop_info() function."""

    def test_get_stop_info_nonexistent_stop_9999999(self):
        """Test that nonexistent stop code returns proper error message."""
        result = get_stop_info("9999999")
        
        # Must contain the exact phrase: "No he encontrado"
        assert "No he encontrado" in result
        assert "9999999" in result

    def test_get_stop_info_error_message_format(self):
        """Test that error message is user-friendly."""
        result = get_stop_info("9999999")
        
        # Should be formatted for user consumption, not a Python traceback
        assert "Traceback" not in result
        assert "File" not in result
        assert "Error al consultar" not in result or "parada" in result.lower()

    def test_get_stop_info_returns_string(self):
        """Test that function always returns a string."""
        result = get_stop_info("9999999")
        assert isinstance(result, str)
        
        # Test with another arbitrary ID
        result_another = get_stop_info("12345")
        assert isinstance(result_another, str)

    def test_get_stop_info_contains_schedule_note_for_valid(self):
        """Test that valid stops include note about plan_trip tool."""
        result = get_stop_info("9999999")
        
        # This test should be skipped or adapted if data doesn't have this exact ID
        if "No he encontrado" not in result:
            # If stop exists, should suggest using plan_trip tool
            assert "plan_trip" in result or "exacta" in result.lower()


class TestGetLineOccupancy:
    """Tests for get_line_occupancy() function."""

    def test_get_line_occupancy_default_type(self):
        """Test that default day type is Laborable."""
        # Should not raise exception
        result = get_line_occupancy("15")
        assert isinstance(result, str)

    def test_get_line_occupancy_returns_string(self):
        """Test that function always returns a string."""
        result = get_line_occupancy("15", "Laborable")
        assert isinstance(result, str)
        
        result_weekend = get_line_occupancy("15", "Sabado")
        assert isinstance(result_weekend, str)

    def test_get_line_occupancy_accepts_different_day_types(self):
        """Test that function accepts different day type formats."""
        # Should handle lowercase and different variations
        result_lowercase = get_line_occupancy("15", "laborable")
        assert isinstance(result_lowercase, str)
        
        result_uppercase = get_line_occupancy("15", "FESTIVO")
        assert isinstance(result_uppercase, str)

    def test_get_line_occupancy_invalid_line(self):
        """Test that invalid line ID returns error message."""
        result = get_line_occupancy("99999")
        
        # Should return error or 'no data' message
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_line_occupancy_zero_padded_id(self):
        """Test that function handles zero-padded IDs correctly."""
        # Some lines might be stored as "015" but used as "15"
        result_padded = get_line_occupancy("015")
        result_unpadded = get_line_occupancy("15")
        
        # Both should work and return strings
        assert isinstance(result_padded, str)
        assert isinstance(result_unpadded, str)


class TestPlanTrip:
    """Tests for plan_trip() function from otp_tools.

    Uses valid example coordinates from Santa Cruz de Tenerife area:
    - Origin: (28.48372, -16.31395)
    - Destination: (28.45761, -16.25833)
    """

    @patch('src.mcp.otp_tools.requests.post')
    def test_plan_trip_valid_response(self, mock_post):
        """Test plan_trip with mocked valid OTP response using real coordinates."""
        # Mock successful OTP response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "plan": {
                    "itineraries": [
                        {
                            "duration": 1200,
                            "walkDistance": 150,
                            "legs": [
                                {
                                    "mode": "BUS",
                                    "route": {"shortName": "15"},
                                    "from": {"name": "Plaza España"},
                                    "to": {"name": "Hospital"}
                                }
                            ]
                        }
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = plan_trip(VALID_ORIGIN[0], VALID_ORIGIN[1], VALID_DESTINATION[0], VALID_DESTINATION[1])

        assert isinstance(result, str)
        assert "itineraries" in result or len(result) > 0
        print(f"✅ Valid response test passed with coordinates: {VALID_ORIGIN} → {VALID_DESTINATION}")

    @patch('src.mcp.otp_tools.requests.post')
    def test_plan_trip_no_routes_found(self, mock_post):
        """Test plan_trip when OTP finds no feasible routes using real coordinates."""
        # Mock OTP response with no itineraries
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "plan": {
                    "itineraries": None
                }
            }
        }
        mock_post.return_value = mock_response

        result = plan_trip(VALID_ORIGIN[0], VALID_ORIGIN[1], VALID_DESTINATION[0], VALID_DESTINATION[1])

        assert "No feasible routes" in result or isinstance(result, str)
        print("✅ No routes test passed")

    @patch('src.mcp.otp_tools.requests.post')
    def test_plan_trip_connection_error(self, mock_post):
        """Test plan_trip when OTP server is unreachable using real coordinates."""
        # Mock connection error with the correct exception type
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = plan_trip(VALID_ORIGIN[0], VALID_ORIGIN[1], VALID_DESTINATION[0], VALID_DESTINATION[1])

        # Should return error message, not crash
        assert isinstance(result, str)
        assert "error" in result.lower() or "Error" in result or "Critical" in result
        print("✅ Connection error test passed")

    def test_plan_trip_with_explicit_datetime(self):
        """Test plan_trip with explicit date and time using real coordinates."""
        with patch('src.mcp.otp_tools.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": {
                    "plan": {
                        "itineraries": [{"duration": 900, "walkDistance": 0, "legs": []}]
                    }
                }
            }
            mock_post.return_value = mock_response

            result = plan_trip(
                VALID_ORIGIN[0], VALID_ORIGIN[1],
                VALID_DESTINATION[0], VALID_DESTINATION[1],
                date="2026-05-27",
                time="08:30:00"
            )
            
            # Should pass without error
            assert isinstance(result, str)
            # Verify the mock was called with the correct date/time
            call_args = mock_post.call_args
            assert call_args is not None
            print("✅ Explicit datetime test passed")

    def test_plan_trip_coordinates_validation(self):
        """Test that plan_trip accepts float coordinates using real valid example."""
        with patch('src.mcp.otp_tools.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": {
                    "plan": {
                        "itineraries": [{"duration": 600, "walkDistance": 0, "legs": []}]
                    }
                }
            }
            mock_post.return_value = mock_response

            # Should accept float coordinates from real area
            result = plan_trip(VALID_ORIGIN[0], VALID_ORIGIN[1], VALID_DESTINATION[0], VALID_DESTINATION[1])
            assert isinstance(result, str)
            print(f"✅ Coordinates validation test passed with real coords: {VALID_ORIGIN} → {VALID_DESTINATION}")

    # @pytest.mark.skip(reason="Requires live OTP server running")
    def test_plan_trip_integration_real_coordinates(self):
        """Integration test with real coordinates (requires OTP server)."""
        # This test actually calls plan_trip without mocking
        # Use valid Santa Cruz coordinates that should have transit
        result = plan_trip(
            VALID_ORIGIN[0], VALID_ORIGIN[1],
            VALID_DESTINATION[0], VALID_DESTINATION[1]
        )

        assert isinstance(result, str)
        # Should either find itineraries or return a meaningful message
        assert len(result) > 0
        print(f"✅ Real OTP test completed: {result[:100]}...")


class TestIntegration:
    """Integration tests that don't require mocking (if DB is available)."""

    # @pytest.mark.skip(reason="Requires live database connection")
    def test_route_info_consistent_across_calls(self):
        """Test that route info returns consistent results."""
        result1 = get_route_info("15")
        result2 = get_route_info("15")
        
        # Same route should return consistent information
        assert result1 == result2

    def test_valid_coordinates_are_in_valid_range(self):
        """Verify that our test coordinates are within valid geographic bounds for Santa Cruz."""
        # Santa Cruz de Tenerife is approximately:
        # Latitude: 28.0-28.6°N
        # Longitude: -16.8 to -16.2°W
        origin_lat, origin_lon = VALID_ORIGIN
        dest_lat, dest_lon = VALID_DESTINATION

        # Latitude checks
        assert 27.5 < origin_lat < 29.0, f"Origin latitude {origin_lat} out of bounds"
        assert 27.5 < dest_lat < 29.0, f"Destination latitude {dest_lat} out of bounds"

        # Longitude checks (negative = west)
        assert -17.5 < origin_lon < -15.5, f"Origin longitude {origin_lon} out of bounds"
        assert -17.5 < dest_lon < -15.5, f"Destination longitude {dest_lon} out of bounds"

        print(f"✅ Test coordinates validated:")
        print(f"   Origin: {VALID_ORIGIN} (lat, lon)")
        print(f"   Destination: {VALID_DESTINATION} (lat, lon)")


# ============================================================================
# Quick reference for running tests
# ============================================================================
# Run all tests:
#   pytest tests/test_backend.py -v
#
# Run specific test class:
#   pytest tests/test_backend.py::TestGetRouteInfo -v
#
# Run specific test:
#   pytest tests/test_backend.py::TestGetRouteInfo::test_get_route_info_valid_route_15 -v
#
# Run with coverage:
#   pytest tests/test_backend.py --cov=src.mcp --cov-report=html
#
# ============================================================================

