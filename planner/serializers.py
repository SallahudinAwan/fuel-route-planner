from rest_framework import serializers


class RoutePlanRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=300, trim_whitespace=True)
    finish = serializers.CharField(max_length=300, trim_whitespace=True)

    def validate(self, attrs):
        if attrs["start"].casefold() == attrs["finish"].casefold():
            raise serializers.ValidationError(
                {"finish": "Finish must be different from start."}
            )
        return attrs
