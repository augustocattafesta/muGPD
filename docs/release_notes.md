# **Release Notes**
----------------

- New data added (23/03/2026) to characterize the noise.
- Added a dispatch in the `fit_spec` task to handle both peak and other spectra fitting. This is useful to fit the noise spectrum in a file without source emission.
- Added new task `noise` to specify if and how to fit and subtract the noise in the low energy region of the spectra.
- Now a copy of the configuration file is saved to the output folder.
- New standard configuration files added in */resources*.
- Renamed some data folders.
- Pull requests merged and issues closed:
    - [PR #63](https://github.com/augustocattafesta/muGPD/pull/63)
    - [PR #64](https://github.com/augustocattafesta/muGPD/pull/64)
    - [PR #66](https://github.com/augustocattafesta/muGPD/pull/66)
    - [PR #67](https://github.com/augustocattafesta/muGPD/pull/67)
    - [Issue #65](https://github.com/augustocattafesta/muGPD/issues/65)

### Version 0.0.3 (2026-03-23)

- Analysis output file refactored.
- Compare tasks refactored into a single compare task that can handle all the different quantities to compare.
- Pull requests merged and issues closed:
    - [PR #60](https://github.com/augustocattafesta/muGPD/pull/60)
    - [PR #62](https://github.com/augustocattafesta/muGPD/pull/62)
    - [Issue #49](https://github.com/augustocattafesta/muGPD/issues/61)

### Version 0.0.2 (2026-03-20)

- Added the package release notes;
- Pull requests merged and issues closed:
    - [PR #57](https://github.com/augustocattafesta/muGPD/pull/57)
    - [Issue #49](https://github.com/augustocattafesta/muGPD/issues/49)