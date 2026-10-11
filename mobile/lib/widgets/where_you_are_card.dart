import 'package:flutter/material.dart';

import '../data/app_scope.dart';
import '../data/location_service.dart';

/// "Right now" card above the Generate button: where you are, the weather
/// there and real spots nearby - what the next quest will be built around.
///
/// Uses the device location (asks for permission when you tap "Use my
/// location" or Generate). If location is off you can type a place into
/// [placeController] instead.
class WhereYouAreCard extends StatefulWidget {
  const WhereYouAreCard({super.key, required this.placeController, required this.distanceKm});

  final TextEditingController placeController;
  final double distanceKm;

  @override
  State<WhereYouAreCard> createState() => _WhereYouAreCardState();
}

class _WhereYouAreCardState extends State<WhereYouAreCard> {
  @override
  void initState() {
    super.initState();
    // Only if permission was given before - no prompt just for opening the tab.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final state = AppScope.read(context);
      if (state.conditions == null && !state.isLocating) {
        state.locate(ask: false, maxTravelKm: widget.distanceKm);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final state = AppScope.of(context);
    final c = state.conditions;
    final w = c?.weather;
    final problem = state.locationProblem;
    final located = state.here != null && problem == null;

    final children = <Widget>[
      Row(
        children: [
          Icon(located ? Icons.my_location : Icons.location_searching, color: theme.colorScheme.primary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              c != null && c.place.isNotEmpty ? c.place : 'Right now',
              key: const Key('where_place'),
              style: theme.textTheme.titleMedium,
            ),
          ),
          if (state.isLocating)
            const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
          else
            IconButton(
              key: const Key('where_refresh'),
              tooltip: 'Use my location',
              onPressed: () => state.locate(maxTravelKm: widget.distanceKm),
              icon: const Icon(Icons.refresh),
            ),
        ],
      ),
    ];

    if (w != null && located) {
      final details = [
        if (w.feelsLikeC != null && (w.feelsLikeC! - w.tempC).abs() >= 2) 'feels like ${w.feelsLikeC!.round()}°C',
        if (w.rainChancePct != null) '${w.rainChancePct}% chance of rain',
        if (w.windKmh != null) 'wind ${w.windKmh!.round()} km/h',
        if (w.isDay == false) 'dark out',
        if (w.airQualityIndex != null && w.airQualityIndex! > 100) 'air quality ${w.airQualityIndex}',
      ];
      children.addAll([
        const SizedBox(height: 4),
        Text(w.short, key: const Key('where_weather'), style: theme.textTheme.titleSmall),
        if (details.isNotEmpty) Text(details.join(' · '), style: muted),
      ]);
    }
    if (c != null && c.nearby.isNotEmpty && located) {
      children.addAll([
        const SizedBox(height: 8),
        Text('Nearby', style: theme.textTheme.labelLarge),
        const SizedBox(height: 4),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final p in c.nearby.take(4))
              Chip(
                visualDensity: VisualDensity.compact,
                avatar: const Icon(Icons.park_outlined, size: 16),
                label: Text('${p.name} · ${p.distanceM} m${p.rating == null ? '' : ' · ${p.rating}'}'),
              ),
          ],
        ),
      ]);
    }
    if (located) {
      children.add(Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Text('Your quest will fit the weather and the places around you.', style: muted),
      ));
    } else {
      final message = switch (problem) {
        null => 'Use your location so quests fit the weather right now and real places nearby.',
        LocationProblem.unavailable => "Couldn't get your location. Try again, or type where you are.",
        final LocationProblem p => LocationException(p).message,
      };
      children.addAll([
        const SizedBox(height: 4),
        Text(message, key: const Key('where_message'), style: muted),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (problem != LocationProblem.deniedForever && problem != LocationProblem.serviceOff)
              OutlinedButton.icon(
                key: const Key('use_my_location'),
                onPressed: state.isLocating ? null : () => state.locate(maxTravelKm: widget.distanceKm),
                icon: const Icon(Icons.my_location),
                label: const Text('Use my location'),
              )
            else
              OutlinedButton.icon(
                key: const Key('open_location_settings'),
                onPressed: () => state.openLocationSettings(),
                icon: const Icon(Icons.settings),
                label: const Text('Open settings'),
              ),
          ],
        ),
        const SizedBox(height: 8),
        TextField(
          key: const Key('place_field'),
          controller: widget.placeController,
          textInputAction: TextInputAction.done,
          decoration: const InputDecoration(
            labelText: 'Or type where you are',
            hintText: 'e.g. Riverdale, Toronto',
            prefixIcon: Icon(Icons.edit_location_alt_outlined),
          ),
        ),
      ]);
    }

    return Card(
      key: const Key('where_you_are_card'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
      ),
    );
  }
}
