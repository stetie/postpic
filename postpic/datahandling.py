#
# This file is part of postpic.
#
# postpic is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# postpic is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with postpic. If not, see <http://www.gnu.org/licenses/>.
#
# Stephan Kuschel, 2014
"""
The Core module for final data handling.

This module provides classes for dealing with axes, grid as well as the Field
class -- the final output of the postpic postprocessor.

Terminology
-----------

A data field with N numeric points has N 'grid' points,
but N+1 'grid_nodes' as depicted here:

+---+---+---+---+---+
|   |   |   |   |   |
+---+---+---+---+---+
|   |   |   |   |   |
+---+---+---+---+---+
|   |   |   |   |   |
+---+---+---+---+---+
  o   o   o   o   o     grid      (coordinates where data is sampled at)
o   o   o   o   o   o   grid_node (coordinates of grid cell boundaries)
|                   |   extent
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np
import copy
from . import helper
from .helper import PhysicalConstants as pc

__all__ = ['Field', 'Axis']


class Axis(object):
    '''
    Axis handling for a single Axis.
    '''

    def __init__(self, name='', unit=''):
        self.name = name
        self.unit = unit
        self._grid_node = np.array([])
        self._linear = None

    def islinear(self, force=False):
        """
        Checks if the axis has a linear grid.
        """
        if self._linear is None or force:
            self._linear = np.var(np.diff(self._grid_node)) < 1e-7
        return self._linear

    @property
    def grid_node(self):
        return self._grid_node

    @grid_node.setter
    def grid_node(self, value):
        gn = np.float64(value)
        if len(gn.shape) != 1:
            raise TypeError('Only 1 dimensional arrays can be assigend.')
        self._grid_node = gn
        self._linear = None

    @property
    def grid(self):
        return np.convolve(self.grid_node, np.ones(2) / 2.0, mode='valid')

    @grid.setter
    def grid(self, grid):
        gn = np.convolve(grid, np.ones(2) / 2.0, mode='full')
        gn[0] = grid[0] + (grid[0] - gn[1])
        gn[-1] = grid[-1] + (grid[-1] - gn[-2])
        self.grid_node = gn

    @property
    def extent(self):
        if len(self._grid_node) < 2:
            ret = None
        else:
            ret = [self._grid_node[0], self._grid_node[-1]]
        return ret

    @property
    def label(self):
        if self.unit == '':
            ret = self.name
        else:
            ret = self.name + ' [' + self.unit + ']'
        return ret

    def setextent(self, extent, n):
        '''
        creates a linear grid with the given extent and n grid points
        (thus n+1 grid_node)
        '''
        if n == 1 and type(extent) is int:
            gn = np.array([extent - 0.5, extent + 0.5])
        else:
            gn = np.linspace(extent[0], extent[-1], n + 1)
        self.grid_node = gn

    def cutout(self, newextent):
        '''
        keeps the grid points within the newextent only.
        '''
        nex = np.sort(newextent)
        gnnew = [gn for gn in self.grid_node
                 if (nex[0] <= gn and gn <= nex[1])]
        self.grid_node = gnnew

    def half_resolution(self):
        '''
        removes every second grid_node.
        '''
        self.grid_node = self.grid_node[::2]

    def __len__(self):
        ret = len(self._grid_node) - 1
        ret = 0 if ret < 0 else ret
        return ret

    def __str__(self):
        return '<Axis "' + str(self.name) + \
               '" (' + str(len(self)) + ' grid points)'


class Field(object):
    '''
    The Field Object carries a data matrix together with as many Axis
    Objects as the data matrix's dimensions. Additionaly the Field object
    provides any information that is necessary to plot _and_ annotate
    the plot. It will also suggest a content based filename for saving.

    {x,y,z}edges can be the edges or grid_nodes given for each dimension. This is
    made to work with np.histogram oder np.histogram2d.
    '''

    def __init__(self, matrix, xedges=None, yedges=None, zedges=None, name='', unit=''):
        if xedges is not None:
            self.matrix = np.asarray(matrix)  # dont sqeeze. trust numpys histogram functions.
        else:
            self.matrix = np.float64(np.squeeze(matrix))
        self.name = name
        self.unit = unit
        self.axes = []
        self.infostring = ''
        self.infos = []
        self._label = None  # autogenerated if None
        if xedges is not None:
            self._addaxisnodes(xedges, name='x')
        elif self.dimensions > 0:
            self._addaxis((0, 1), name='x')
        if yedges is not None:
            self._addaxisnodes(yedges, name='y')
        elif self.dimensions > 1:
            self._addaxis((0, 1), name='y')
        if zedges is not None:
            self._addaxisnodes(zedges, name='z')
        elif self.dimensions > 2:
            self._addaxis((0, 1), name='z')

    def _addaxisobj(self, axisobj):
        '''
        uses the given axisobj as the axis obj in the given dimension.
        '''
        # check if number of grid points match
        matrixpts = self.matrix.shape[len(self.axes)]
        if matrixpts != len(axisobj):
            raise ValueError(
                'Number of Grid points in next missing Data '
                'Dimension ({:d}) has to match number of grid points of '
                'new axis ({:d})'.format(matrixpts, len(axisobj)))
        self.axes.append(axisobj)

    def _addaxisnodes(self, grid_node, **kwargs):
        ax = Axis(**kwargs)
        ax.grid_node = grid_node
        self._addaxisobj(ax)
        return

    def _addaxis(self, extent, **kwargs):
        '''
        adds a new axis that is supported by the matrix.
        '''
        matrixpts = self.matrix.shape[len(self.axes)]
        ax = Axis(**kwargs)
        ax.setextent(extent, matrixpts)
        self._addaxisobj(ax)

    def _fft(self, k0, axes=None):
        '''
        applies the fast fourier transform (FFT) to the field object and returns a new
        transformed field. Currently, only 2D fields are supported. Both axes are 
        transformed, but the axis gives by axes is shifted in such a way, that
        the 0 component is in the middle. The frequencies are given in terms
        of k0, which has to be defined by the user.
        '''
        if k0 is None:
            raise ValueError('No k0 specified.')
        if not (self.dimensions == 2):
            raise ValueError('This function is only available for 2D fields.')
        rfftaxes = np.roll((0, 1), axes)
        ret = copy.deepcopy(self)
        ret.matrix = 0.5 * pc.epsilon0 * abs(np.fft.fftshift(np.fft.rfft2(self.matrix,
                                                                    axes=rfftaxes), axes=axes))**2
        ret.unit = '?'
        ret.name = 'FFT of {0}'.format(self.name)
        # Assuming all axes are spatial (x, y, z) coordinates. 
        # This might not be true for all cases, further checks are needed
        for axid in rfftaxes:
            ax = ret.axes[axid]
            # only linear axes can be transformed
            if ax.islinear():
                ax.name = r'$k_{0} / k_0$'.format(ax.name)
                ax.unit = ''
                dx = ax.grid_node[1]-ax.grid_node[0]
                freq = np.fft.rfftfreq(len(ax.grid_node), dx)
                if axid == axes:
                    freq_extent = np.array([-freq[-1]/2., freq[-1]/2.])
                else:
                    freq_extent = np.array([freq[0], freq[-1]])
                ax.setextent(freq_extent, len(freq))
            else:
                raise ValueError('Specified axis is not linear.')
        return ret
        
    def fft(self, k0=1, axes=1):
        return self._fft(k0, axes)

    def setaxisobj(self, axis, axisobj):
        '''
        replaces the current axisobject for axis axis by the
        new axisobj axisobj.
        '''
        axid = helper.axesidentify[axis]
        if not len(axisobj) == self.matrix.shape[axid]:
            raise ValueError('Axis object has {:3n} grid points, whereas '
                             'the data matrix has {:3n} on axis {:1n}'
                             ''.format(len(axisobj),
                                       self.matrix.shape[axid], axid))
        self.axes[axid] = axisobj

    def islinear(self):
        return [a.islinear() for a in self.axes]

    @property
    def label(self):
        if self._label:
            ret = self._label
        elif self.unit == '':
            ret = self.name
        else:
            ret = self.name + ' [' + self.unit + ']'
        return ret

    @label.setter
    def label(self, x):
        self._label = x
        return

    @property
    def shape(self):
        return self.matrix.shape

    @property
    def grid_nodes(self):
        return np.squeeze([a.grid_node for a in self.axes])

    @property
    def grid(self):
        return np.squeeze([a.grid for a in self.axes])

    @property
    def dimensions(self):
        '''
        returns only present dimensions.
        [] and [[]] are interpreted as -1
        np.array(2) is interpreted as 0
        np.array([1,2,3]) is interpreted as 1
        and so on...
        '''
        ret = len(self.matrix.shape)  # works for everything with data.
        if np.prod(self.matrix.shape) == 0:  # handels everything without data
            ret = -1
        return ret

    @property
    def extent(self):
        '''
        returns the extents in a linearized form,
        as required by "matplotlib.pyplot.imshow".
        '''
        return np.ravel([a.extent for a in self.axes])

    @extent.setter
    def extent(self, newextent):
        '''
        sets the new extent to the specific values
        '''
        assert self.dimensions * 2 == len(newextent), \
            'size of newextent doesnt match self.dimensions * 2'
        for i in range(len(self.axes)):
            self.axes[i].setextent(newextent[2 * i:2 * i + 2],
                                   self.matrix.shape[i])
        return

    def half_resolution(self, axis):
        '''
        Halfs the resolution along the given axis by removing
        every second grid_node and averaging every second data point into one.

        if there is an odd number of grid points, the last point will
        be ignored. (that means, the extent will change by the size of
        the last grid cell)
        '''
        axis = helper.axesidentify[axis]
        self.axes[axis].half_resolution()
        n = self.matrix.ndim
        s = [slice(None), ] * n
        # ignore last grid point if self.matrix.shape[axis] is odd
        lastpt = self.matrix.shape[axis] - self.matrix.shape[axis] % 2
        # Averaging over neighboring points
        s[axis] = slice(0, lastpt, 2)
        ret = self.matrix[s]
        s[axis] = slice(1, lastpt, 2)
        ret += self.matrix[s]
        self.matrix = ret / 2.0
        return

    def autoreduce(self, maxlen=4000):
        '''
        Reduces the Grid to a maximum length of maxlen per dimension
        by just executing half_resolution as often as necessary.
        '''
        for i in range(len(self.axes)):
            if len(self.axes[i]) > maxlen:
                self.half_resolution(i)
                self.autoreduce(maxlen=maxlen)
                break
        return self

    def cutout(self, newextent):
        '''
        only keeps that part of the matrix, that belongs to newextent.
        '''
        if self.dimensions == 0:
            return
        assert self.dimensions * 2 == len(newextent), \
            'size of newextent doesnt match self.dimensions * 2'
        self.matrix = helper.cutout(self.matrix, self.extent, newextent)
        for i in range(len(self.axes)):
            self.axes[i].cutout(newextent[2 * i:2 * i + 2])
        return

    def mean(self, axis=-1):
        '''
        takes the mean along the given axis.
        '''
        if self.dimensions == 0:
            return self
        self.matrix = np.mean(self.matrix, axis=axis)
        self.axes.pop(axis)
        return self

    def topolar(self, extent=None, shape=None, angleoffset=0):
        '''
        remaps the current kartesian coordinates to polar coordinates
        extent should be given as extent=(phimin, phimax, rmin, rmax)
        '''
        ret = copy.deepcopy(self)
        if extent is None:
            extent = [-np.pi, np.pi, 0, self.extent[1]]
        extent = np.asarray(extent)
        if shape is None:
            maxpt_r = np.min((np.floor(np.min(self.matrix.shape) / 2), 1000))
            shape = (1000, maxpt_r)

        extent[0:2] = extent[0:2] - angleoffset
        ret.matrix = helper.transfromxy2polar(self.matrix, self.extent,
                                              np.roll(extent, 2), shape).T
        extent[0:2] = extent[0:2] + angleoffset

        ret.extent = extent
        if ret.axes[0].name.startswith('$k_') \
           and ret.axes[1].name.startswith('$k_'):
            ret.axes[0].name = '$k_\phi$'
            ret.axes[1].name = '$|k|$'
        return ret

    def exporttocsv(self, filename):
        if self.dimensions == 1:
            data = np.asarray(self.matrix)
            x = np.linspace(self.extent[0], self.extent[1], len(data))
            np.savetxt(filename, np.transpose([x, data]), delimiter=' ')
        elif self.dimensions == 2:
            export = np.asarray(self.matrix)
            np.savetxt(filename, export)
        else:
            raise Exception('Not Implemented')
        return

    def __str__(self):
        return '<Feld "' + self.name + '" ' + str(self.matrix.shape) + '>'

    # Operator overloading
    def __iadd__(self, other):
        if isinstance(other, Field):
            self.matrix += other.matrix
            self.name = self.name + ' + ' + other.name
        else:
            self.matrix += other
        return self

    def __add__(self, other):
        ret = copy.deepcopy(self)
        ret += other
        return ret

    def __neg__(self):
        ret = copy.deepcopy(self)
        ret.matrix *= -1
        return ret

    def __isub__(self, other):
        if isinstance(other, Field):
            self.matrix -= other.matrix
            self.name = self.name + ' - ' + other.name
        else:
            self.matrix -= other
        return self

    def __sub__(self, other):
        ret = copy.deepcopy(self)
        ret -= other
        return ret

    def __pow__(self, other):
        ret = copy.deepcopy(self)
        ret.matrix = self.matrix ** other
        return ret

    def __imul__(self, other):
        if isinstance(other, Field):
            self.matrix *= other.matrix
            self.name = self.name + ' * ' + other.name
        else:
            self.matrix *= other
        return self

    def __mul__(self, other):
        ret = copy.deepcopy(self)
        ret *= other
        return ret

    def __abs__(self):
        ret = copy.deepcopy(self)
        ret.matrix = np.abs(ret.matrix)
        return ret

    # self /= other: normalization
    def __itruediv__(self, other):
        if isinstance(other, Field):
            self.matrix /= other.matrix
            self.name = self.name + ' / ' + other.name
        else:
            self.matrix /= other
        return self

    def __truediv__(self, other):
        ret = copy.deepcopy(self)
        ret /= other
        return ret

    # python 2
    __idiv__ = __itruediv__
    __div__ = __truediv__


