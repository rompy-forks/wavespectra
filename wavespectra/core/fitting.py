import numpy as np
from scipy.optimize import curve_fit

from wavespectra.fit.jonswap import np_jonswap
from wavespectra.fit.gaussian import np_gaussian

def _fit_jonswap(ef, freq, fp0, hs0, gamma0=1.5):
    """Nonlinear fit Jonswap spectrum.

    Args:
        - ef (1darray): Frequency wave spectrum to fit (m2/Hz).
        - freq (1darray): Frequency array (Hz).
        - fp0 (float): Peak frequency first guess (Hz).
        - hs0 (float): Significant wave height first guess (m).
        - gamma0 (float): Peak enhancement factor first guess.

    Returns:
        - p1 (list): Fitted values for hs, fp and gamma.

    """
    import warnings
    from scipy.optimize import OptimizeWarning # Covariance - warning make nans for unreliable fits
    
    with warnings.catch_warnings():
        warnings.filterwarnings("error")
        
        if np.isnan(fp0) or (hs0<1E-10):
            p1 = np.array([np.nan,]*3)
        else:
            try:
                p1, cov = curve_fit(
                    f=np_jonswap,
                    xdata=freq,
                    ydata=ef,
                    p0=[fp0, hs0, gamma0],
                    bounds=(np.array([np.min(freq),1E-10,0.1]),np.array([np.max(freq),30.,20.]))
                )
            except (ValueError, RuntimeError):
                p1 = np.array([np.nan,]*3)
            except OptimizeWarning:
                p1 = np.array([np.nan,]*3)

    return p1


def fit_jonswap_spectra(ef, freq, fp0, hs0, gamma0):
    """Wrapper to return only spectrum from _fit_jonswap to run as ufunc."""
    fp, hs, gamma = _fit_jonswap(ef, freq, fp0, hs0, gamma0)
    return np_jonswap(freq, fp, hs, gamma)


def fit_jonswap_gamma(ef, freq, fp0, hs0, gamma0):
    """Wrapper to return only gamma from _fit_jonswap to run as ufunc."""
    return _fit_jonswap(ef, freq, fp0, hs0, gamma0)[-1]


def _fit_gaussian(ef, freq, fp0, hs0, gw):
    """Nonlinear fit Gaussian spectrum.

    Args:
        - ef (1darray): Frequency wave spectrum to fit (m2/Hz).
        - freq (1darray): Frequency array (Hz).
        - fp0 (float): Peak frequency first guess (Hz).
        - hs0 (float): Significant wave height first guess (m).
        - gamma0 (float): Peak enhancement factor first guess.

    Returns:
        - p1 (list): Fitted values for hs, fp and gamma.

    """
    import warnings
    from scipy.optimize import OptimizeWarning # Covariance - warning make nans for unreliable fits
    
    with warnings.catch_warnings():
        warnings.filterwarnings("error")

        if np.isnan(fp0) or (hs0<1E-10):
            p1 = np.array([np.nan,]*3)
        else:
            try:
                p1, cov = curve_fit(
                    f=np_gaussian,
                    xdata=freq,
                    ydata=ef,
                    p0=[fp0, hs0, gw],
                )
            except (ValueError, RuntimeError):
                p1 = np.array([np.nan,]*3)
            except OptimizeWarning:
                p1 = np.array([np.nan,]*3)
        
    return p1


def fit_gaussian_spectra(ef, freq, fp0, hs0, gw0):
    """Wrapper to return only spectrum from _fit_gaussian to run as ufunc."""
    fp, hs, gw = _fit_gaussian(ef, freq, fp0, hs0, gw0)
    return np_gaussian(freq, fp, hs, gw)


def fit_gaussian_gw(ef, freq, fp0, hs0, gw0):
    """Wrapper to return only gw from _fit_gaussian to run as ufunc."""
    return _fit_gaussian(ef, freq, fp0, hs0, gw0)[-1]