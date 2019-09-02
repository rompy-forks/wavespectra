"""Modified from xarray.

Changes include:
    - get_axis() redefined to initialise polar axes

Use this module directly:
    import xarray.plot as xplt

Or use the methods on a DataArray or Dataset:
    DataArray.plot._____

"""
import functools
import warnings
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import xarray as xr
from matplotlib.projections import PolarAxes
from xarray.plot.facetgrid import _easy_facetgrid
from xarray.plot.utils import (
    _add_colorbar,
    _ensure_plottable,
    _infer_interval_breaks,
    _infer_xy_labels,
    _interval_to_double_bound_points,
    _interval_to_mid_points,
    _process_cmap_cbar_kwargs,
    _rescale_imshow_rgb,
    _resolve_intervals_2dplot,
    _update_axes,
    _valid_other_type,
    import_matplotlib_pyplot,
    label_from_attrs,
)

from wavespectra.core.attributes import attrs


def get_axis(figsize, size, aspect, ax, subplot_kw={}):
    """Returns axis instance to use with _plot2d."""
    if figsize is not None:
        if ax is not None:
            raise ValueError("cannot provide both `figsize` and " "`ax` arguments")
        if size is not None:
            raise ValueError("cannot provide both `figsize` and " "`size` arguments")
        _, ax = plt.subplots(figsize=figsize, subplot_kw=subplot_kw)
    elif size is not None:
        if ax is not None:
            raise ValueError("cannot provide both `size` and `ax` arguments")
        if aspect is None:
            width, height = mpl.rcParams["figure.figsize"]
            aspect = width / height
        figsize = (size * aspect, size)
        _, ax = plt.subplots(figsize=figsize, subplot_kw=subplot_kw)
    elif aspect is not None:
        raise ValueError("cannot provide `aspect` argument without `size`")

    if ax is None:
        ax = plt.gca(projection=subplot_kw.get("projection", None))

    return ax


def _transpose_spectral_coordinates(darray):
    """Swap ordem of frequency and direction coordinates in dataarray."""
    dims = list(darray.dims)
    ifreq = dims.index(attrs.FREQNAME)
    idir = dims.index(attrs.DIRNAME)
    dims[ifreq], dims[idir] = dims[idir], dims[ifreq]
    return darray.transpose(*dims, transpose_coords=True)


def _wrap_and_sort_directions(darray):
    """Wrap directions for polar plot."""
    if darray[attrs.DIRNAME][0] % 360 == darray[attrs.DIRNAME][-1] % 360:
        return darray.sortby(attrs.DIRNAME)
    darray = darray.sortby(attrs.DIRNAME)
    dd = np.diff(darray[attrs.DIRNAME]).mean()
    darray = xr.concat((darray, darray.isel(**{attrs.DIRNAME: 0})), dim=attrs.DIRNAME)
    darray[attrs.DIRNAME].values[-1] = darray[attrs.DIRNAME].values[-2] + dd
    return darray


def _freq_or_period_clean_attributes(darray, as_period=False):
    """Define lean spectral attributes for clean plot."""
    darray[attrs.DIRNAME].attrs.update({"standard_name": "Wave direction"})
    if as_period:
        if darray[attrs.FREQNAME].attrs["standard_name"] != "Wave period":
            darray[attrs.FREQNAME] = 1. / darray[attrs.FREQNAME]
        darray[attrs.FREQNAME].attrs.update({"standard_name": "Wave period", "units": "s"})
    else:
        darray[attrs.FREQNAME].attrs.update({"standard_name": "Wave frequency"})
    return darray


def _infer_line_data(darray, x, y, hue):
    error_msg = "must be either None or one of ({:s})".format(
        ", ".join([repr(dd) for dd in darray.dims])
    )
    ndims = len(darray.dims)

    if x is not None and x not in darray.dims and x not in darray.coords:
        raise ValueError("x " + error_msg)

    if y is not None and y not in darray.dims and y not in darray.coords:
        raise ValueError("y " + error_msg)

    if x is not None and y is not None:
        raise ValueError("You cannot specify both x and y kwargs" "for line plots.")

    if ndims == 1:
        huename = None
        hueplt = None
        huelabel = ""

        if x is not None:
            xplt = darray[x]
            yplt = darray

        elif y is not None:
            xplt = darray
            yplt = darray[y]

        else:  # Both x & y are None
            dim = darray.dims[0]
            xplt = darray[dim]
            yplt = darray

    else:
        if x is None and y is None and hue is None:
            raise ValueError("For 2D inputs, please" "specify either hue, x or y.")

        if y is None:
            xname, huename = _infer_xy_labels(darray=darray, x=x, y=hue)
            xplt = darray[xname]
            if xplt.ndim > 1:
                if huename in darray.dims:
                    otherindex = 1 if darray.dims.index(huename) == 0 else 0
                    otherdim = darray.dims[otherindex]
                    yplt = darray.transpose(otherdim, huename, transpose_coords=False)
                    xplt = xplt.transpose(otherdim, huename, transpose_coords=False)
                else:
                    raise ValueError(
                        "For 2D inputs, hue must be a dimension"
                        " i.e. one of " + repr(darray.dims)
                    )

            else:
                yplt = darray.transpose(xname, huename)

        else:
            yname, huename = _infer_xy_labels(darray=darray, x=y, y=hue)
            yplt = darray[yname]
            if yplt.ndim > 1:
                if huename in darray.dims:
                    otherindex = 1 if darray.dims.index(huename) == 0 else 0
                    otherdim = darray.dims[otherindex]
                    xplt = darray.transpose(otherdim, huename, transpose_coords=False)
                else:
                    raise ValueError(
                        "For 2D inputs, hue must be a dimension"
                        " i.e. one of " + repr(darray.dims)
                    )

            else:
                xplt = darray.transpose(yname, huename)

        huelabel = label_from_attrs(darray[huename])
        hueplt = darray[huename]

    xlabel = label_from_attrs(xplt)
    ylabel = label_from_attrs(yplt)

    return xplt, yplt, hueplt, xlabel, ylabel, huelabel


def plot(
    darray,
    row=None,
    col=None,
    col_wrap=None,
    ax=None,
    hue=None,
    rtol=0.01,
    subplot_kws=None,
    **kwargs
):
    """
    Default plot of DataArray using matplotlib.pyplot.

    Calls xarray plotting function based on the dimensions of
    darray.squeeze()

    =============== ===========================
    Dimensions      Plotting function
    --------------- ---------------------------
    1               :py:func:`xarray.plot.line`
    2               :py:func:`xarray.plot.pcolormesh`
    Anything else   :py:func:`xarray.plot.hist`
    =============== ===========================

    Parameters
    ----------
    darray : DataArray
    row : string, optional
        If passed, make row faceted plots on this dimension name
    col : string, optional
        If passed, make column faceted plots on this dimension name
    hue : string, optional
        If passed, make faceted line plots with hue on this dimension name
    col_wrap : integer, optional
        Use together with ``col`` to wrap faceted plots
    ax : matplotlib axes, optional
        If None, uses the current axis. Not applicable when using facets.
    rtol : number, optional
        Relative tolerance used to determine if the indexes
        are uniformly spaced. Usually a small positive number.
    subplot_kws : dict, optional
        Dictionary of keyword arguments for matplotlib subplots. Only applies
        to FacetGrid plotting.
    **kwargs : optional
        Additional keyword arguments to matplotlib

    """
    darray = darray.squeeze().compute()

    plot_dims = set(darray.dims)
    plot_dims.discard(row)
    plot_dims.discard(col)
    plot_dims.discard(hue)

    ndims = len(plot_dims)

    error_msg = (
        "Only 1d and 2d plots are supported for facets in xarray. "
        "See the package `Seaborn` for more options."
    )

    if ndims in [1, 2]:
        if row or col:
            kwargs["row"] = row
            kwargs["col"] = col
            kwargs["col_wrap"] = col_wrap
            kwargs["subplot_kws"] = subplot_kws
        if ndims == 1:
            plotfunc = line
            kwargs["hue"] = hue
        elif ndims == 2:
            if hue:
                plotfunc = line
                kwargs["hue"] = hue
            else:
                plotfunc = pcolormesh
    else:
        if row or col or hue:
            raise ValueError(error_msg)
        plotfunc = hist

    kwargs["ax"] = ax

    return plotfunc(darray, **kwargs)


# This function signature should not change so that it can use
# matplotlib format strings
def line(
    darray,
    *args,
    row=None,
    col=None,
    figsize=None,
    aspect=None,
    size=None,
    ax=None,
    hue=None,
    x=None,
    y=None,
    xincrease=None,
    yincrease=None,
    xscale=None,
    yscale=None,
    xticks=None,
    yticks=None,
    xlim=None,
    ylim=None,
    add_legend=True,
    _labels=True,
    **kwargs
):
    """
    Line plot of DataArray index against values

    Wraps :func:`matplotlib:matplotlib.pyplot.plot`

    Parameters
    ----------
    darray : DataArray
        Must be 1 dimensional
    figsize : tuple, optional
        A tuple (width, height) of the figure in inches.
        Mutually exclusive with ``size`` and ``ax``.
    aspect : scalar, optional
        Aspect ratio of plot, so that ``aspect * size`` gives the width in
        inches. Only used if a ``size`` is provided.
    size : scalar, optional
        If provided, create a new figure for the plot with the given size.
        Height (in inches) of each plot. See also: ``aspect``.
    ax : matplotlib axes object, optional
        Axis on which to plot this figure. By default, use the current axis.
        Mutually exclusive with ``size`` and ``figsize``.
    hue : string, optional
        Dimension or coordinate for which you want multiple lines plotted.
        If plotting against a 2D coordinate, ``hue`` must be a dimension.
    x, y : string, optional
        Dimensions or coordinates for x, y axis.
        Only one of these may be specified.
        The other coordinate plots values from the DataArray on which this
        plot method is called.
    xscale, yscale : 'linear', 'symlog', 'log', 'logit', optional
        Specifies scaling for the x- and y-axes respectively
    xticks, yticks : Specify tick locations for x- and y-axes
    xlim, ylim : Specify x- and y-axes limits
    xincrease : None, True, or False, optional
        Should the values on the x axes be increasing from left to right?
        if None, use the default for the matplotlib function.
    yincrease : None, True, or False, optional
        Should the values on the y axes be increasing from top to bottom?
        if None, use the default for the matplotlib function.
    add_legend : boolean, optional
        Add legend with y axis coordinates (2D inputs only).
    *args, **kwargs : optional
        Additional arguments to matplotlib.pyplot.plot
    """
    # Handle facetgrids first
    if row or col:
        allargs = locals().copy()
        allargs.update(allargs.pop("kwargs"))
        allargs.pop("darray")
        return _easy_facetgrid(darray, line, kind="line", **allargs)

    ndims = len(darray.dims)
    if ndims > 2:
        raise ValueError(
            "Line plots are for 1- or 2-dimensional DataArrays. "
            "Passed DataArray has {ndims} "
            "dimensions".format(ndims=ndims)
        )

    # The allargs dict passed to _easy_facetgrid above contains args
    if args is ():
        args = kwargs.pop("args", ())
    else:
        assert "args" not in kwargs

    ax = get_axis(figsize, size, aspect, ax, subplot_kw={})
    xplt, yplt, hueplt, xlabel, ylabel, hue_label = _infer_line_data(darray, x, y, hue)

    # Remove pd.Intervals if contained in xplt.values.
    if _valid_other_type(xplt.values, [pd.Interval]):
        # Is it a step plot? (see matplotlib.Axes.step)
        if kwargs.get("linestyle", "").startswith("steps-"):
            xplt_val, yplt_val = _interval_to_double_bound_points(
                xplt.values, yplt.values
            )
            # Remove steps-* to be sure that matplotlib is not confused
            kwargs["linestyle"] = (
                kwargs["linestyle"]
                .replace("steps-pre", "")
                .replace("steps-post", "")
                .replace("steps-mid", "")
            )
            if kwargs["linestyle"] == "":
                del kwargs["linestyle"]
        else:
            xplt_val = _interval_to_mid_points(xplt.values)
            yplt_val = yplt.values
            xlabel += "_center"
    else:
        xplt_val = xplt.values
        yplt_val = yplt.values

    _ensure_plottable(xplt_val, yplt_val)

    primitive = ax.plot(xplt_val, yplt_val, *args, **kwargs)

    if _labels:
        if xlabel is not None:
            ax.set_xlabel(xlabel)

        if ylabel is not None:
            ax.set_ylabel(ylabel)

        ax.set_title(darray._title_for_slice())

    if darray.ndim == 2 and add_legend:
        ax.legend(handles=primitive, labels=list(hueplt.values), title=hue_label)

    # Rotate dates on xlabels
    # Do this without calling autofmt_xdate so that x-axes ticks
    # on other subplots (if any) are not deleted.
    # https://stackoverflow.com/questions/17430105/autofmt-xdate-deletes-x-axis-labels-of-all-subplots
    if np.issubdtype(xplt.dtype, np.datetime64):
        for xlabels in ax.get_xticklabels():
            xlabels.set_rotation(30)
            xlabels.set_ha("right")

    _update_axes(ax, xincrease, yincrease, xscale, yscale, xticks, yticks, xlim, ylim)

    return primitive


def step(darray, *args, where="pre", linestyle=None, ls=None, **kwargs):
    """
    Step plot of DataArray index against values

    Similar to :func:`matplotlib:matplotlib.pyplot.step`

    Parameters
    ----------
    where : {'pre', 'post', 'mid'}, optional, default 'pre'
        Define where the steps should be placed:
        - 'pre': The y value is continued constantly to the left from
          every *x* position, i.e. the interval ``(x[i-1], x[i]]`` has the
          value ``y[i]``.
        - 'post': The y value is continued constantly to the right from
          every *x* position, i.e. the interval ``[x[i], x[i+1])`` has the
          value ``y[i]``.
        - 'mid': Steps occur half-way between the *x* positions.
        Note that this parameter is ignored if the x coordinate consists of
        :py:func:`pandas.Interval` values, e.g. as a result of
        :py:func:`xarray.Dataset.groupby_bins`. In this case, the actual
        boundaries of the interval are used.

    *args, **kwargs : optional
        Additional arguments following :py:func:`xarray.plot.line`
    """
    if where not in {"pre", "post", "mid"}:
        raise ValueError("'where' argument to step must be " "'pre', 'post' or 'mid'")

    if ls is not None:
        if linestyle is None:
            linestyle = ls
        else:
            raise TypeError("ls and linestyle are mutually exclusive")
    if linestyle is None:
        linestyle = ""
    linestyle = "steps-" + where + linestyle

    return line(darray, *args, linestyle=linestyle, **kwargs)


def hist(
    darray,
    figsize=None,
    size=None,
    aspect=None,
    ax=None,
    xincrease=None,
    yincrease=None,
    xscale=None,
    yscale=None,
    xticks=None,
    yticks=None,
    xlim=None,
    ylim=None,
    **kwargs
):
    """
    Histogram of DataArray

    Wraps :func:`matplotlib:matplotlib.pyplot.hist`

    Plots N dimensional arrays by first flattening the array.

    Parameters
    ----------
    darray : DataArray
        Can be any dimension
    figsize : tuple, optional
        A tuple (width, height) of the figure in inches.
        Mutually exclusive with ``size`` and ``ax``.
    aspect : scalar, optional
        Aspect ratio of plot, so that ``aspect * size`` gives the width in
        inches. Only used if a ``size`` is provided.
    size : scalar, optional
        If provided, create a new figure for the plot with the given size.
        Height (in inches) of each plot. See also: ``aspect``.
    ax : matplotlib axes object, optional
        Axis on which to plot this figure. By default, use the current axis.
        Mutually exclusive with ``size`` and ``figsize``.
    **kwargs : optional
        Additional keyword arguments to matplotlib.pyplot.hist

    """
    ax = get_axis(figsize, size, aspect, ax, subplot_kw={})

    no_nan = np.ravel(darray.values)
    no_nan = no_nan[pd.notnull(no_nan)]

    primitive = ax.hist(no_nan, **kwargs)

    ax.set_title("Histogram")
    ax.set_xlabel(label_from_attrs(darray))

    _update_axes(ax, xincrease, yincrease, xscale, yscale, xticks, yticks, xlim, ylim)

    return primitive


# MUST run before any 2d plotting functions are defined since
# _plot2d decorator adds them as methods here.
class _PlotMethods:
    """
    Enables use of xarray.plot functions as attributes on a DataArray.
    For example, DataArray.plot.imshow
    """

    __slots__ = ("_da",)

    def __init__(self, darray):
        self._da = darray

    def __call__(self, **kwargs):
        return plot(self._da, **kwargs)

    @functools.wraps(hist)
    def hist(self, ax=None, **kwargs):
        return hist(self._da, ax=ax, **kwargs)

    @functools.wraps(line)
    def line(self, *args, **kwargs):
        return line(self._da, *args, **kwargs)

    @functools.wraps(step)
    def step(self, *args, **kwargs):
        return step(self._da, *args, **kwargs)


def _plot2d(plotfunc):
    """
    Decorator for common 2d plotting logic

    Also adds the 2d plot method to class _PlotMethods
    """
    commondoc = """
    Parameters
    ----------
    darray : DataArray
        Must be 2 dimensional, unless creating faceted plots
    x : string, optional
        Coordinate for x axis. If None use darray.dims[1]
    y : string, optional
        Coordinate for y axis. If None use darray.dims[0]
    projection : string, optional
        Axis projection.
    show_radius_label: Bolean, optional
        Display the radius labels
    show_direction_label: Bolean, optional
        Display the direction labels
    as_period : Boolean, optional
        Plot spectra as period instead of frequency.
    rmax : Float, optional
        Maximum radius if polar axis.
    as_log10 : Boolean, optional
        Plot the log10 of the spectrum for better visualisation.
    figsize : tuple, optional
        A tuple (width, height) of the figure in inches.
        Mutually exclusive with ``size`` and ``ax``.
    aspect : scalar, optional
        Aspect ratio of plot, so that ``aspect * size`` gives the width in
        inches. Only used if a ``size`` is provided.
    size : scalar, optional
        If provided, create a new figure for the plot with the given size.
        Height (in inches) of each plot. See also: ``aspect``.
    ax : matplotlib axes object, optional
        Axis on which to plot this figure. By default, use the current axis.
        Mutually exclusive with ``size`` and ``figsize``.
    row : string, optional
        If passed, make row faceted plots on this dimension name
    col : string, optional
        If passed, make column faceted plots on this dimension name
    col_wrap : integer, optional
        Use together with ``col`` to wrap faceted plots
    xscale, yscale : 'linear', 'symlog', 'log', 'logit', optional
        Specifies scaling for the x- and y-axes respectively
    xticks, yticks : Specify tick locations for x- and y-axes
    xlim, ylim : Specify x- and y-axes limits
    xincrease : None, True, or False, optional
        Should the values on the x axes be increasing from left to right?
        if None, use the default for the matplotlib function.
    yincrease : None, True, or False, optional
        Should the values on the y axes be increasing from top to bottom?
        if None, use the default for the matplotlib function.
    add_colorbar : Boolean, optional
        Adds colorbar to axis
    add_labels : Boolean, optional
        Use xarray metadata to label axes
    norm : ``matplotlib.colors.Normalize`` instance, optional
        If the ``norm`` has vmin or vmax specified, the corresponding kwarg
        must be None.
    vmin, vmax : floats, optional
        Values to anchor the colormap, otherwise they are inferred from the
        data and other keyword arguments. When a diverging dataset is inferred,
        setting one of these values will fix the other by symmetry around
        ``center``. Setting both values prevents use of a diverging colormap.
        If discrete levels are provided as an explicit list, both of these
        values are ignored.
    cmap : matplotlib colormap name or object, optional
        The mapping from data values to color space. If not provided, this
        will be either be ``viridis`` (if the function infers a sequential
        dataset) or ``RdBu_r`` (if the function infers a diverging dataset).
        When `Seaborn` is installed, ``cmap`` may also be a `seaborn`
        color palette. If ``cmap`` is seaborn color palette and the plot type
        is not ``contour`` or ``contourf``, ``levels`` must also be specified.
    colors : discrete colors to plot, optional
        A single color or a list of colors. If the plot type is not ``contour``
        or ``contourf``, the ``levels`` argument is required.
    center : float, optional
        The value at which to center the colormap. Passing this value implies
        use of a diverging colormap. Setting it to ``False`` prevents use of a
        diverging colormap.
    robust : bool, optional
        If True and ``vmin`` or ``vmax`` are absent, the colormap range is
        computed with 2nd and 98th percentiles instead of the extreme values.
    extend : {'neither', 'both', 'min', 'max'}, optional
        How to draw arrows extending the colorbar beyond its limits. If not
        provided, extend is inferred from vmin, vmax and the data limits.
    levels : int or list-like object, optional
        Split the colormap (cmap) into discrete color intervals. If an integer
        is provided, "nice" levels are chosen based on the data range: this can
        imply that the final number of levels is not exactly the expected one.
        Setting ``vmin`` and/or ``vmax`` with ``levels=N`` is equivalent to
        setting ``levels=np.linspace(vmin, vmax, N)``.
    infer_intervals : bool, optional
        Only applies to pcolormesh. If True, the coordinate intervals are
        passed to pcolormesh. If False, the original coordinates are used
        (this can be useful for certain map projections). The default is to
        always infer intervals, unless the mesh is irregular and plotted on
        a map projection.
    subplot_kws : dict, optional
        Dictionary of keyword arguments for matplotlib subplots. Only applies
        to FacetGrid plotting.
    cbar_ax : matplotlib Axes, optional
        Axes in which to draw the colorbar.
    cbar_kwargs : dict, optional
        Dictionary of keyword arguments to pass to the colorbar.
    **kwargs : optional
        Additional arguments to wrapped matplotlib function

    Returns
    -------
    artist :
        The same type of primitive artist that the wrapped matplotlib
        function returns
    """

    # Build on the original docstring
    plotfunc.__doc__ = "%s\n%s" % (plotfunc.__doc__, commondoc)

    @functools.wraps(plotfunc)
    def newplotfunc(
        darray,
        x=None,
        y=None,
        projection="polar",
        show_radius_label=True,
        show_direction_label=False,
        as_period=False,
        as_log10=True,
        rmax=None,
        figsize=None,
        size=None,
        aspect=None,
        ax=None,
        row=None,
        col=None,
        col_wrap=None,
        xincrease=True,
        yincrease=True,
        add_colorbar=None,
        add_labels=True,
        vmin=None,
        vmax=None,
        cmap=None,
        center=None,
        robust=False,
        extend=None,
        levels=None,
        infer_intervals=None,
        colors=None,
        subplot_kws=None,
        cbar_ax=None,
        cbar_kwargs=None,
        xscale=None,
        yscale=None,
        xticks=None,
        yticks=None,
        xlim=None,
        ylim=None,
        norm=None,
        **kwargs
    ):
        # All 2d plots in xarray share this function signature.
        # Method signature below should be consistent.

        # Default colormap
        if cmap is None:
            try:
                from cmocean import cm
                cmap = cm.thermal
            except:
                warnings.warn("cmocean not installed, cannot set default colormap cmocean.cm.thermal")
                pass

        # Prepare dataarray for polar plotting
        if projection == "polar":
            darray = _wrap_and_sort_directions(darray)
            darray = _freq_or_period_clean_attributes(darray, as_period=as_period)
            if np.diff(darray.get_axis_num([attrs.FREQNAME, attrs.DIRNAME])) < 0:
                darray = _transpose_spectral_coordinates(darray)
            if rmax is not None:
                darray = darray.sel(**{attrs.FREQNAME: slice(None, rmax)})

        # Log values make it easier to view multiple wave systems in spectrum
        # Try and ensure that log won't be calculated twice if facet grids
        if as_log10:
            if not (darray.min() == -5 and 0 not in darray.values):
                darray.values = np.log10(darray.where(darray.values>0).fillna(0.00001))

        # Decide on a default for the colorbar before facetgrids
        if add_colorbar is None:
            add_colorbar = plotfunc.__name__ != "contour"
        imshow_rgb = plotfunc.__name__ == "imshow" and darray.ndim == (
            3 + (row is not None) + (col is not None)
        )
        if imshow_rgb:
            # Don't add a colorbar when showing an image with explicit colors
            add_colorbar = False
            # Matplotlib does not support normalising RGB data, so do it here.
            # See eg. https://github.com/matplotlib/matplotlib/pull/10220
            if robust or vmax is not None or vmin is not None:
                darray = _rescale_imshow_rgb(darray, vmin, vmax, robust)
                vmin, vmax, robust = None, None, False

        # Handle facetgrids first
        if row or col:
            allargs = locals().copy()
            del allargs["darray"]
            del allargs["imshow_rgb"]
            allargs.update(allargs.pop("kwargs"))
            # Need the decorated plotting function
            allargs["plotfunc"] = globals()[plotfunc.__name__]
            # subplot_kws to allow polar facet grids
            subplot_kws = allargs.pop("subplot_kws", {}) or {}
            subplot_kws.update({"projection": projection})
            allargs["subplot_kws"] = subplot_kws
            # Removed local variables to avoid warnings
            allargs.pop("cm", None)
            allargs.pop("projection", None)
            return _easy_facetgrid(darray, kind="dataarray", **allargs)

        plt = import_matplotlib_pyplot()

        rgb = kwargs.pop("rgb", None)
        if rgb is not None and plotfunc.__name__ != "imshow":
            raise ValueError('The "rgb" keyword is only valid for imshow()')
        elif rgb is not None and not imshow_rgb:
            raise ValueError(
                'The "rgb" keyword is only valid for imshow()'
                "with a three-dimensional array (per facet)"
            )

        xlab, ylab = _infer_xy_labels(
            darray=darray, x=x, y=y, imshow=imshow_rgb, rgb=rgb
        )

        # better to pass the ndarrays directly to plotting functions
        xval = darray[xlab].values
        yval = darray[ylab].values

        # check if we need to broadcast one dimension
        if xval.ndim < yval.ndim:
            xval = np.broadcast_to(xval, yval.shape)

        if yval.ndim < xval.ndim:
            yval = np.broadcast_to(yval, xval.shape)

        # May need to transpose for correct x, y labels
        # xlab may be the name of a coord, we have to check for dim names
        if imshow_rgb:
            # For RGB[A] images, matplotlib requires the color dimension
            # to be last.  In Xarray the order should be unimportant, so
            # we transpose to (y, x, color) to make this work.
            yx_dims = (ylab, xlab)
            dims = yx_dims + tuple(d for d in darray.dims if d not in yx_dims)
            if dims != darray.dims:
                darray = darray.transpose(*dims, transpose_coords=True)
        elif darray[xlab].dims[-1] == darray.dims[0]:
            darray = darray.transpose(transpose_coords=True)

        # Pass the data as a masked ndarray too
        zval = darray.to_masked_array(copy=False)

        # Replace pd.Intervals if contained in xval or yval.
        xplt, xlab_extra = _resolve_intervals_2dplot(xval, plotfunc.__name__)
        yplt, ylab_extra = _resolve_intervals_2dplot(yval, plotfunc.__name__)

        # Convert coordinates if polar
        if projection == "polar":
            xplt, yplt = np.meshgrid(np.deg2rad(xplt), yplt)

        _ensure_plottable(xplt, yplt)

        cmap_params, cbar_kwargs = _process_cmap_cbar_kwargs(
            plotfunc, zval.data, **locals()
        )

        if "contour" in plotfunc.__name__:
            # extend is a keyword argument only for contour and contourf, but
            # passing it to the colorbar is sufficient for imshow and
            # pcolormesh
            kwargs["extend"] = cmap_params["extend"]
            kwargs["levels"] = cmap_params["levels"]
            # if colors == a single color, matplotlib draws dashed negative
            # contours. we lose this feature if we pass cmap and not colors
            if isinstance(colors, str):
                cmap_params["cmap"] = None
                kwargs["colors"] = colors

        if "pcolormesh" == plotfunc.__name__:
            kwargs["infer_intervals"] = infer_intervals

        if "imshow" == plotfunc.__name__ and isinstance(aspect, str):
            # forbid usage of mpl strings
            raise ValueError(
                "plt.imshow's `aspect` kwarg is not available " "in xarray"
            )

        ax = get_axis(figsize, size, aspect, ax, subplot_kw={"projection": projection})
        primitive = plotfunc(
            xplt,
            yplt,
            zval,
            ax=ax,
            cmap=cmap_params["cmap"],
            vmin=cmap_params["vmin"],
            vmax=cmap_params["vmax"],
            norm=cmap_params["norm"],
            **kwargs
        )

        # Label the plot with metadata
        if add_labels:
            ax.set_xlabel(label_from_attrs(darray[xlab], xlab_extra))
            ax.set_ylabel(label_from_attrs(darray[ylab], ylab_extra))
            ax.set_title(darray._title_for_slice())

        # Make polar axis Nautical
        if projection == "polar":
            ax.set_theta_zero_location("N")
            ax.set_theta_direction(-1)
            # ax.set_rticks(np.arange(0, rmax+4, 4))
            if not show_direction_label:
                ax.set_xticklabels([])
            if not show_radius_label:
                ax.set_yticklabels([])

        if add_colorbar:
            if add_labels and "label" not in cbar_kwargs:
                cbar_kwargs["label"] = label_from_attrs(darray)
            cbar = _add_colorbar(primitive, ax, cbar_ax, cbar_kwargs, cmap_params)
        elif cbar_ax is not None or cbar_kwargs:
            # inform the user about keywords which aren't used
            raise ValueError(
                "cbar_ax and cbar_kwargs can't be used with " "add_colorbar=False."
            )

        # origin kwarg overrides yincrease
        if "origin" in kwargs:
            yincrease = None

        _update_axes(
            ax, xincrease, yincrease, xscale, yscale, xticks, yticks, xlim, ylim
        )

        # Rotate dates on xlabels
        # Do this without calling autofmt_xdate so that x-axes ticks
        # on other subplots (if any) are not deleted.
        # https://stackoverflow.com/questions/17430105/autofmt-xdate-deletes-x-axis-labels-of-all-subplots
        if np.issubdtype(xplt.dtype, np.datetime64):
            for xlabels in ax.get_xticklabels():
                xlabels.set_rotation(30)
                xlabels.set_ha("right")

        return primitive

    # For use as DataArray.plot.plotmethod
    @functools.wraps(newplotfunc)
    def plotmethod(
        _PlotMethods_obj,
        x=None,
        y=None,
        projection="polar",
        show_radius_label=True,
        show_direction_label=False,
        as_period=False,
        as_log10=True,
        rmax=None,
        figsize=None,
        size=None,
        aspect=None,
        ax=None,
        row=None,
        col=None,
        col_wrap=None,
        xincrease=True,
        yincrease=True,
        add_colorbar=None,
        add_labels=True,
        vmin=None,
        vmax=None,
        cmap=None,
        colors=None,
        center=None,
        robust=False,
        extend=None,
        levels=None,
        infer_intervals=None,
        subplot_kws=None,
        cbar_ax=None,
        cbar_kwargs=None,
        xscale=None,
        yscale=None,
        xticks=None,
        yticks=None,
        xlim=None,
        ylim=None,
        norm=None,
        **kwargs
    ):
        """
        The method should have the same signature as the function.

        This just makes the method work on Plotmethods objects,
        and passes all the other arguments straight through.
        """
        allargs = locals()
        allargs["darray"] = _PlotMethods_obj._da
        allargs.update(kwargs)
        for arg in ["_PlotMethods_obj", "newplotfunc", "kwargs"]:
            del allargs[arg]
        return newplotfunc(**allargs)

    # Add to class _PlotMethods
    setattr(_PlotMethods, plotmethod.__name__, plotmethod)

    return newplotfunc


@_plot2d
def imshow(x, y, z, ax, **kwargs):
    """
    Image plot of 2d DataArray using matplotlib.pyplot

    Wraps :func:`matplotlib:matplotlib.pyplot.imshow`

    While other plot methods require the DataArray to be strictly
    two-dimensional, ``imshow`` also accepts a 3D array where some
    dimension can be interpreted as RGB or RGBA color channels and
    allows this dimension to be specified via the kwarg ``rgb=``.

    Unlike matplotlib, Xarray can apply ``vmin`` and ``vmax`` to RGB or RGBA
    data, by applying a single scaling factor and offset to all bands.
    Passing  ``robust=True`` infers ``vmin`` and ``vmax``
    :ref:`in the usual way <robust-plotting>`.

    .. note::
        This function needs uniformly spaced coordinates to
        properly label the axes. Call DataArray.plot() to check.

    The pixels are centered on the coordinates values. Ie, if the coordinate
    value is 3.2 then the pixels for those coordinates will be centered on 3.2.
    """

    if x.ndim != 1 or y.ndim != 1:
        raise ValueError(
            "imshow requires 1D coordinates, try using " "pcolormesh or contour(f)"
        )

    # Centering the pixels- Assumes uniform spacing
    try:
        xstep = (x[1] - x[0]) / 2.0
    except IndexError:
        # Arbitrary default value, similar to matplotlib behaviour
        xstep = 0.1
    try:
        ystep = (y[1] - y[0]) / 2.0
    except IndexError:
        ystep = 0.1
    left, right = x[0] - xstep, x[-1] + xstep
    bottom, top = y[-1] + ystep, y[0] - ystep

    defaults = {"origin": "upper", "interpolation": "nearest"}

    if not hasattr(ax, "projection"):
        # not for cartopy geoaxes
        defaults["aspect"] = "auto"

    # Allow user to override these defaults
    defaults.update(kwargs)

    if defaults["origin"] == "upper":
        defaults["extent"] = [left, right, bottom, top]
    else:
        defaults["extent"] = [left, right, top, bottom]

    if z.ndim == 3:
        # matplotlib imshow uses black for missing data, but Xarray makes
        # missing data transparent.  We therefore add an alpha channel if
        # there isn't one, and set it to transparent where data is masked.
        if z.shape[-1] == 3:
            alpha = np.ma.ones(z.shape[:2] + (1,), dtype=z.dtype)
            if np.issubdtype(z.dtype, np.integer):
                alpha *= 255
            z = np.ma.concatenate((z, alpha), axis=2)
        else:
            z = z.copy()
        z[np.any(z.mask, axis=-1), -1] = 0

    primitive = ax.imshow(z, **defaults)

    return primitive


@_plot2d
def contour(x, y, z, ax, clean_radius=False, clean_sector=False, **kwargs):
    """
    Contour plot of 2d DataArray

    Wraps :func:`matplotlib:matplotlib.pyplot.contour`
    """
    primitive = ax.contour(x, y, z, **kwargs)
    if clean_radius:
        ax.set_rticks([])
    if clean_sector:
        ax.set_xticks([])
    return primitive


@_plot2d
def contourf(x, y, z, ax, clean_radius=False, clean_sector=False, **kwargs):
    """
    Filled contour plot of 2d DataArray

    Wraps :func:`matplotlib:matplotlib.pyplot.contourf`
    """
    primitive = ax.contourf(x, y, z, **kwargs)
    if clean_radius:
        ax.set_rticks([])
    if clean_sector:
        ax.set_xticks([])
    return primitive


@_plot2d
def pcolormesh(x, y, z, ax, infer_intervals=None, clean_radius=False, clean_sector=False, **kwargs):
    """
    Pseudocolor plot of 2d DataArray

    Wraps :func:`matplotlib:matplotlib.pyplot.pcolormesh`
    """

    # decide on a default for infer_intervals (GH781)
    x = np.asarray(x)
    if infer_intervals is None:
        if hasattr(ax, "projection"):
            if len(x.shape) == 1:
                infer_intervals = True
            else:
                infer_intervals = False
        else:
            infer_intervals = True

    if infer_intervals and (
        (np.shape(x)[0] == np.shape(z)[1])
        or ((x.ndim > 1) and (np.shape(x)[1] == np.shape(z)[1]))
    ):
        if len(x.shape) == 1:
            x = _infer_interval_breaks(x, check_monotonic=True)
        else:
            # we have to infer the intervals on both axes
            x = _infer_interval_breaks(x, axis=1)
            x = _infer_interval_breaks(x, axis=0)

    if infer_intervals and (np.shape(y)[0] == np.shape(z)[0]):
        if len(y.shape) == 1:
            y = _infer_interval_breaks(y, check_monotonic=True)
        else:
            # we have to infer the intervals on both axes
            y = _infer_interval_breaks(y, axis=1)
            y = _infer_interval_breaks(y, axis=0)

    primitive = ax.pcolormesh(x, y, z, **kwargs)

    # by default, pcolormesh picks "round" values for bounds
    # this results in ugly looking plots with lots of surrounding whitespace
    if not hasattr(ax, "projection") and x.ndim == 1 and y.ndim == 1:
        # not a cartopy geoaxis
        ax.set_xlim(x[0], x[-1])
        ax.set_ylim(y[0], y[-1])

    if clean_radius:
        ax.set_rticks([])
    if clean_sector:
        ax.set_xticks([])

    return primitive


#TODO: Clean up unecessary stuff, import from xarray

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    from wavespectra import read_swan

    dset = read_swan("../tests/sample_files/swanfile.spec", as_site=True)

    darr = dset.isel(site=0).efth.sortby("dir") #.isel(time=0)
    # fig = plt.figure()
    # darr.spec.plot.contourf(x="dir", y="freq", col="time", col_wrap=3, levels=15)
    contourf(darr, x="dir", y="freq", col='time', col_wrap=2, as_log10=True, levels=15, add_colorbar=False,
             show_direction_label=False, as_period=False, rmax=0.2, clean_radius=True, clean_sector=True)
    # contourf(darr.isel(time=0), x="dir", y="freq", levels=15)#, cmap='viridis')

    plt.show()
