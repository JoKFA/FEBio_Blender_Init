# Questions and data requests for the lab

Goal for v0.1: drive the lab's jaw asset with one precomputed landmark trajectory, simulate it in FEBio instead of Ziva, play it back in Blender, and compare against the same trajectory run in Ziva.

## Questions (short answers are enough)

1. **How do landmarks drive the tissue in Ziva?** Are the bound vertices moved directly (hard constraint), or do landmark joints carry small bones that pull the tissue through attachments with a stiffness? This decides how we model landmarks in FEBio.
2. **Is Ziva in the optimization loop?** In the analytical-gradient version, is Ziva only used for the final forward playback, or queried at every optimization step?
3. **Units of the jaw asset.** The paper uses 1 Maya unit = 0.0962 cm for the full head. Same for the jaw asset?
4. **Ziva settings we need to match:** tissue material type and parameters (Young's modulus, Poisson ratio, density), tet resolution, attachment pairs with stiffness and weight maps, solver settings (substeps, gravity, damping).
5. **Timing:** when does the Ziva license expire? Can reference runs be exported before then?
6. **Asset license:** can we use the shared asset for this project? We will keep it out of any repository.

## Data requests

| # | What | Format | Why |
|---|---|---|---|
| D1 | The jaw asset: skull, mandible, teeth, lips, attachments | Maya scene with Ziva nodes preferred; otherwise meshes plus the settings in Q4 | The scene we rebuild in FEBio |
| D2 | One precomputed trajectory, e.g. Neutral → AA | Landmark-to-vertex binding weights, per-frame landmark transforms, per-frame jaw rotation | The input we drive FEBio with |
| D3 | Ziva output for the same trajectory | Per-frame lip vertex positions (Alembic or cache) | The reference we compare against |
| D4 | Tolerance | e.g. mean / max vertex error in mm | Defines "matches Ziva" |
| D5 | Later: the controller code that calls Maya | Source or the interface functions | Porting the controller to the new backend |
