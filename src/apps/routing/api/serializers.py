from __future__ import annotations

from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(min_length=2, max_length=255, trim_whitespace=True)
    destination = serializers.CharField(min_length=2, max_length=255, trim_whitespace=True)

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        if attrs["start"].casefold() == attrs["destination"].casefold():
            raise serializers.ValidationError("start and destination must be different")
        return attrs


class LocationResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    display_name = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class RouteResponseSerializer(serializers.Serializer):
    start = LocationResponseSerializer()
    destination = LocationResponseSerializer()
    distance_miles = serializers.FloatField(min_value=0)
    duration_minutes = serializers.FloatField(min_value=0)
    geometry = serializers.JSONField()


class VehicleResponseSerializer(serializers.Serializer):
    max_range_miles = serializers.FloatField()
    mpg = serializers.FloatField()
    tank_capacity_gallons = serializers.FloatField()
    starting_fuel_gallons = serializers.FloatField()


class FuelResponseSerializer(serializers.Serializer):
    total_gallons = serializers.FloatField(min_value=0)
    total_gallons_purchased = serializers.FloatField(min_value=0)
    total_cost = serializers.FloatField(min_value=0)
    stops_count = serializers.IntegerField(min_value=0)
    ending_fuel_gallons = serializers.FloatField(min_value=0)


class FuelStopResponseSerializer(serializers.Serializer):
    station_id = serializers.CharField()
    station_name = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    price_per_gallon = serializers.FloatField(min_value=0)
    distance_along_route_miles = serializers.FloatField(min_value=0)
    gallons_purchased = serializers.FloatField(min_value=0)
    cost = serializers.FloatField(min_value=0)


class RoutePlanResponseSerializer(serializers.Serializer):
    route = RouteResponseSerializer()
    vehicle = VehicleResponseSerializer()
    fuel = FuelResponseSerializer()
    stops = FuelStopResponseSerializer(many=True)
