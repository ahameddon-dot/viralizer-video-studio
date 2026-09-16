# Motion Director test report

Generated from the implemented engine. These are the exact final prompts produced by the six required scenarios.

## Vinyl UI rotation

- Scene type: `UI_ANIMATION`
- Generation type: `image_to_video`
- Camera: `LOCKED`
- Motion budget: `15`

Animate the supplied source image for 5 seconds as a ui animation scene about Dreamy vinyl record music player interface. Treat the source image as the absolute visual truth: preserve its composition, crop, camera perspective, subject placement, background layout, color palette, lighting direction and all visible design details. Preservation is strict for composition, framing, geometry, text and colors; identity=NORMAL, pose=NORMAL, UI=STRICT. Vinyl record (primary, subtle): rotate clockwise continuously at a slow constant turntable speed, approximately one complete rotation every 2–3 seconds; keep it anchored to record center axis, parent rotating disc, driven by turntable motor. Center label or album artwork (secondary, subtle): rotate at exactly the same angular speed with no sliding or independent drift; keep it anchored to record center axis, attached_to record and inherits_motion, driven by record rotation. Tonearm, controls, typography and remaining interface (locked, locked): remain completely fixed, crisp, readable and unchanged; keep it anchored to original coordinates, independent locked layer, driven by none. Record highlights and soft glow (reactive, micro): move subtly with the rotating surface; keep it anchored to record surface, reacts_to rotation, driven by record rotation. Use a 15/100 motion budget: prioritize the primary motion first, then secondary and reactive motion only when it remains physically connected; omit optional motion before exceeding the budget. No camera movement, zoom, pan, tilt, orbit, perspective shift or reframing; keep the camera completely locked. End strategy: seamless loop: return naturally to a frame compatible with the opening pose and state. Avoid morphing or geometry drift; duplicated or disappearing objects; flicker or abrupt camera motion; do not alter, rewrite, regenerate or move any text, number, icon, button or panel; new interface elements.

## MOBA idle character

- Scene type: `GAMING`
- Generation type: `image_to_video`
- Camera: `LOCKED`
- Motion budget: `20`

Animate the supplied source image for 5 seconds as a gaming scene about MOBA hero character selection screen. Treat the source image as the absolute visual truth: preserve its composition, crop, camera perspective, subject placement, background layout, color palette, lighting direction and all visible design details. Preservation is strict for composition, framing, geometry, text and colors; identity=STRICT, pose=STRICT, UI=STRICT. Hero character (primary, subtle): natural breathing and minute posture settling without changing the pose; keep it anchored to feet and body center, parent character rig, driven by breathing. Hair, cloth strips and loose costume parts (secondary, micro): gentle delayed sway with believable inertia; keep it anchored to attachment points, attached_to character and inherits_motion, driven by body settling and ambient air. Energy, particles and reflections (reactive, micro): restrained pulsing and drifting along existing effect paths; keep it anchored to existing effect origins, reacts_to character energy, driven by ambient energy. HUD, stats, currency, labels, buttons, portraits and icons (locked, locked): remain pixel-stable, readable and unchanged; keep it anchored to screen coordinates, independent locked layer, driven by none. Use a 20/100 motion budget: prioritize the primary motion first, then secondary and reactive motion only when it remains physically connected; omit optional motion before exceeding the budget. No camera movement, zoom, pan, tilt, orbit, perspective shift or reframing; keep the camera completely locked. End strategy: seamless loop: return naturally to a frame compatible with the opening pose and state. Avoid morphing or geometry drift; duplicated or disappearing objects; flicker or abrupt camera motion; do not alter, rewrite, regenerate or move any text, number, icon, button or panel; new interface elements; do not change facial identity, anatomy, costume design or pose; lip movement unless speech is explicitly requested.

## Product advertisement

- Scene type: `PRODUCT`
- Generation type: `image_to_video`
- Camera: `SUBTLE`
- Motion budget: `35`

Animate the supplied source image for 5 seconds as a product scene about Luxury fragrance product commercial. Treat the source image as the absolute visual truth: preserve its composition, crop, camera perspective, subject placement, background layout, color palette, lighting direction and all visible design details. Preservation is strict for composition, framing, geometry, text and colors; identity=NORMAL, pose=NORMAL, UI=NORMAL. Product (primary, subtle): remain geometrically exact while highlights travel slowly across the material; keep it anchored to product center, geometry-locked object, driven by controlled studio light. Supporting particles or fabric (secondary, micro): restrained motion that frames rather than covers the product; keep it anchored to existing contact points, reacts_to product reveal, driven by air displacement. Surface reflections and shadows (reactive, subtle): respond consistently to the camera and key light; keep it anchored to product surfaces, reacts_to light and camera, driven by camera movement. Use a 35/100 motion budget: prioritize the primary motion first, then secondary and reactive motion only when it remains physically connected; omit optional motion before exceeding the budget. Use one very slow controlled push-in, with no orbit or lens change. End strategy: hero end: settle on a clean, stable final product composition. Avoid morphing or geometry drift; duplicated or disappearing objects; flicker or abrupt camera motion; do not redesign the product, mechanism or vehicle; logo, material, proportion or part-count changes.

## Human portrait

- Scene type: `PORTRAIT`
- Generation type: `image_to_video`
- Camera: `MICRO`
- Motion budget: `20`

Animate the supplied source image for 5 seconds as a portrait scene about Editorial portrait of a creator. Treat the source image as the absolute visual truth: preserve its composition, crop, camera perspective, subject placement, background layout, color palette, lighting direction and all visible design details. Preservation is strict for composition, framing, geometry, text and colors; identity=STRICT, pose=STRICT, UI=NORMAL. Person (primary, micro): subtle breathing, one natural blink and an almost imperceptible eye refocus; keep it anchored to face and torso, identity-locked subject, driven by natural life motion. Hair and fabric edges (secondary, micro): minimal delayed movement without obscuring the face; keep it anchored to attachment points, attached_to person, driven by breath and ambient air. Background depth (optional, micro): soft optical bokeh drift only; keep it anchored to background plane, independent, driven by ambient light. Use a 20/100 motion budget: prioritize the primary motion first, then secondary and reactive motion only when it remains physically connected; omit optional motion before exceeding the budget. Use only an almost imperceptible cinematic push-in; preserve the original framing and perspective. End strategy: seamless loop: return naturally to a frame compatible with the opening pose and state. Avoid morphing or geometry drift; duplicated or disappearing objects; flicker or abrupt camera motion; do not change facial identity, anatomy, costume design or pose; lip movement unless speech is explicitly requested.

## Moving car

- Scene type: `AUTOMOTIVE`
- Generation type: `image_to_video`
- Camera: `CONTROLLED`
- Motion budget: `55`

Animate the supplied source image for 5 seconds as a automotive scene about Premium automotive car driving on a coastal road. Treat the source image as the absolute visual truth: preserve its composition, crop, camera perspective, subject placement, background layout, color palette, lighting direction and all visible design details. Preservation is strict for composition, framing, geometry, text and colors; identity=NORMAL, pose=NORMAL, UI=NORMAL. Vehicle body (primary, normal): move forward with stable design, proportions, badges and body panels; keep it anchored to vehicle center of mass, parent vehicle, driven by engine propulsion. Wheels (secondary, normal): rotate around each wheel axle at the exact speed implied by travel; keep it anchored to wheel axles, attached_to vehicle and inherits translation, driven by vehicle movement. Road, reflections and environment (reactive, normal): show consistent parallax, moving reflections and light direction; keep it anchored to world coordinates, reacts_to vehicle speed, driven by vehicle travel. Use a 55/100 motion budget: prioritize the primary motion first, then secondary and reactive motion only when it remains physically connected; omit optional motion before exceeding the budget. Use one smooth tracking move matched to the vehicle speed; avoid sudden acceleration or angle changes. End strategy: hero end: settle on a clean, stable final product composition. Avoid morphing or geometry drift; duplicated or disappearing objects; flicker or abrupt camera motion; do not redesign the product, mechanism or vehicle; logo, material, proportion or part-count changes.

## Generic cinematic scene

- Scene type: `CINEMATIC`
- Generation type: `text_to_video`
- Camera: `CONTROLLED`
- Motion budget: `55`

Create a 5-second vertical 9:16 cinematic video about A cinematic documentary about a city changing at sunrise. Visual intent: Reveal a human-scale transformation. Build one coherent scene with a clear focal subject, stable spatial layout, realistic materials, and enough depth for natural motion. Keep subject identity, object geometry, wardrobe, palette, lighting direction and environment consistent throughout the shot. Main subject (primary, normal): perform one clear physically believable action; keep it anchored to subject center of mass, parent subject, driven by story intent. Secondary elements (secondary, subtle): respond with delayed natural inertia; keep it anchored to attachment or contact points, reacts_to main subject, driven by primary action. Environment (reactive, subtle): continue restrained coherent background motion; keep it anchored to world space, reacts_to action, driven by subject movement. Use a 55/100 motion budget: prioritize the primary motion first, then secondary and reactive motion only when it remains physically connected; omit optional motion before exceeding the budget. Use one motivated, smooth camera move only, then settle into a stable end frame. End strategy: natural end: complete the action and settle without freezing unnaturally. Avoid morphing or geometry drift; duplicated or disappearing objects; flicker or abrupt camera motion.
