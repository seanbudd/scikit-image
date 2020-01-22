import numpy as np
from scipy import ndimage as ndi
from scipy.optimize import minimize

from .pyramids import pyramid_gaussian
from ..metrics import normalized_mutual_information

__all__ = ['register_affine']


def _parameter_vector_to_matrix(parameter_vector, ndim):
    """
    Converts the optimisation parameters to a 3x3 transformation matrix

    The optimisation paramters are known as the parameter_vector and are
    composed of the first ``ndim`` rows of the transformation matrix, as
    that is all that is used in an affine transformation.

    Parameters
    ----------
    parameter_vector : (ndim*(ndim+1)) array
        Input array giving the argument for the minimize function to
        optimise against.
    ndim : int
        The dimensionality of the space being transformed.

    Returns
    -------
    matrix : (ndim+1, ndim+1) array
        A transformation matrix used to affine-map coordinates in an
        ``ndim``-dimensional space.
    """
    top_matrix = np.reshape(parameter_vector, (ndim, ndim+1))
    bottom_row = np.array([[0] * ndim + [1]])
    return np.concatenate((top_matrix, bottom_row), axis=0)


def _matrix_to_parameter_vector(matrix):
    """
    Converts a (N+1)x(N+1) transformation matrix to the optimisation parameters

    See the inverse function `_parameter_vector_to_matrix`.

    Parameters
    ----------
    matrix : (N+1, N+1) array
        A transformation matrix used to obtain a new image

    Returns
    -------
    parameter_vector : (N*(N+1)) array
        Output array giving the argument of the minimum function to
        optimise against

    """

    return matrix[:-1, :].ravel()


def cost_nmi(image0, image1, *, bins=100):
    """Negative of the normalized mutual information.

    See :func:`skimage.metrics.normalized_mutual_information` for more info.

    Parameters
    ----------
    image0, image1 : array
        The images to be compared. They should have the same shape.
    bins : int or sequence of int, optional
        The granularity of the histogram with which to compare the images.
        If it's a sequence, each number is the number of bins for that image.

    Returns
    -------
    cnmi : float
        The negative of the normalized mutual information between ``image0``
        and ``image1``.
    """
    return -normalized_mutual_information(image0, image1, bins=bins)


def register_affine(reference, moving, *, cost=cost_nmi, minimum_size=8,
                    multichannel=False, inverse=True,
                    level_callback=None, method='Powell', **kwargs):
    """Find a transformation matrix to register a target image to a reference.

    Parameters
    ----------
    reference : ndimage
        A reference image to compare against the target.
    moving : ndimage
        Our target for registration. Transforming this image using the
        returned matrix aligns it with the reference.
    cost : function, optional
        A cost function which takes two images and returns a score which is
        at a minimum when images are aligned. Uses the normalized mutual
        information by default.
    minimum_size : integer, optional
        The smallest size for an image along any dimension. This value
        determines the size of the image pyramid used. Choosing a smaller value
        here can cause registration errors, but a larger value could speed up
        registration when the alignment is easy.
    multichannel : bool, optional
        Whether the last axis of the image is to be interpreted as multiple
        channels or another spatial dimension. By default, this is False.
    inverse : bool, optional
        Whether to return the inverse transform, which converts coordinates
        in the reference space to coordinates in the target space. For
        technical reasons, this is the transform expected by
        ``scipy.ndimage.affine_transform`` to map the target image to the
        reference space.
    level_callback : callable, optional
        If given, this function is called once per pyramid level with a tuple
        containing the current downsampled image, transformation matrix, and
        cost as the argument. This is useful for debugging or for plotting
        intermediate results during the iterative process.
    method : string
        Method of minimization.  See ``scipy.optimize.minimize`` for available
        options.
    **kwargs : keyword arguments
        Keyword arguments passed through to ``scipy.optimize.minimize``

    Returns
    -------
    matrix : array
        A transformation matrix used to obtain a new image.
        ndi.affine_transform(target, matrix) will align your target image.

    Example
    -------
    >>> from skimage.data import astronaut
    >>> reference_image = astronaut()[..., 1]
    >>> r = -0.12  # radians
    >>> c, s = np.cos(r), np.sin(r)
    >>> matrix_transform = np.array([[c, -s, 0], [s, c, 50], [0, 0, 1]])
    >>> target_image = ndi.affine_transform(reference_image, matrix_transform)
    >>> matrix = register_affine(reference_image, target_image)
    >>> registered_target = ndi.affine_transform(target_image, matrix)
    """

    # ignore the channels if present
    ndim = reference.ndim if not multichannel else reference.ndim - 1
    if ndim == 0:
        raise ValueError(
            'Input images must have at least 1 spatial dimension.')

    min_dim = min(reference.shape[:ndim])
    nlevels = int(np.floor(np.log2(min_dim) - np.log2(minimum_size)))

    pyramid_ref = pyramid_gaussian(reference, max_layer=nlevels,
                                   multichannel=multichannel)
    pyramid_mvg = pyramid_gaussian(moving, max_layer=nlevels,
                                   multichannel=multichannel)
    image_pairs = reversed(list(zip(pyramid_ref, pyramid_mvg)))
    parameter_vector = _matrix_to_parameter_vector(np.identity(ndim + 1))

    for ref, mvg in image_pairs:
        def _cost(param):
            transformation = _parameter_vector_to_matrix(param, ndim)
            if not multichannel:
                transformed = ndi.affine_transform(mvg, transformation,
                                                   order=1)
            else:
                transformed = np.zeros_like(mvg)
                for ch in range(mvg.shape[-1]):
                    ndi.affine_transform(mvg[..., ch], transformation,
                                         order=1, output=transformed[..., ch])
            return cost(ref, transformed)

        result = minimize(_cost, x0=parameter_vector, method=method, **kwargs)
        parameter_vector = result.x
        if level_callback is not None:
            level_callback(
                (mvg,
                 _parameter_vector_to_matrix(parameter_vector, ndim),
                 result.fun)
            )

    matrix = _parameter_vector_to_matrix(parameter_vector, ndim)

    if not inverse:
        # estimated is already inverse, so we invert for forward transform
        matrix = np.linalg.inv(matrix)

    return matrix
