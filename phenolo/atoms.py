# -*- coding: utf-8 -*-

import logging

import numpy as np
import pandas as pd
import scipy.interpolate as interpolate
import copy
logger = logging.getLogger(__name__)
from numba import jit

class PixelDrill(object):
    """
    Pixel drill:

    a single pixel drill represent the minimum unit of analysis
    """

    def __init__(self, ts, px):
        self.ts_raw = ts
        self.position = px
        self.tst = None
        self.ts_filtered = None
        self.ts_interpolated = None
        self.season_ts = None
        self.season_lng = None
        self.expSeason = None
        self.trend_ts = None
        self.medspan = None
        self.ts_d = None
        self.ts_sv = None
        self.mpd_val = None
        self.pks = None
        self.seasons = None
        self.sincys = []
        self.error = None
        self.phen = []
        self.error = False
        self.errtyp = None

        # pd.dataframes with years indexes
        self.stb = None  # Standing biomass
        self.mpi = None  # Minimum minimum permanent Integrals
        self.sbd = None  # Seasons beginning dates
        self.sed = None  # Seasons end dates
        self.sl = None  # Seasons lengths dates
        self.spi = None  # Seasons Permanent Integrals
        self.si = None  # Seasons integrals
        self.cf = None  # Seasons cyclic fractions
        self.afi = None  # Season Active Fraction
        self.warn = None  # Warning flags
        
    def __del__(self):
        for ith in self.__dict__.keys():
            setattr(self, ith, None)

    def int_cleaner(self):
        self.ts_raw = None
        self.tst = None
        self.ts_interpolated = None
        self.season_lng = None
        self.expSeason = None
        self.trend_ts = None
        self.medspan = None
        self.ts_sv = None
        self.mpd_val = None

        self.ts = None
        self.ts_resc = None
        self.ts_cleaned = None
        self.ts_filtered = None
        self.seasons = None
        self.trend = None
        self.ts_d = None
        self.trend_d = None
        self.ps = None
        self.pks = None
        self.sincys = None
        self.phen = None
        

class SingularCycle(object):

    def __init__(self, ts, sd, ed):
        """
        Rappresent a singular cycle defined as the curve between two minima

        Attributes:
            mms: minimum minimum time series
            mms_b : minimum minimum time series buffered by timdelta 2/3
            sd: Start date - MBD
            ed: End date - MED
            mml: Cycle lenght in days
            td: Time delta
            sb: Standing biomas
            mpf: permanent fration
            mpi: permanent fration
            vox: Values between two minima substracted the permanet fraction
            voxi: integral
            cbc: cycle baricenter / ex season baricenter
            csd: cycle deviation standard / Season deviation standard
            cdsdcycle: deviation standard in days /Season deviation standard in days
            max_idx: date of maximum
            ref_yr: reference yr

            sb: Seasons beginning dates [Posix ns]
            se:Seasons end dates [Posix ns]
            sl:Seasons lengths dates [ns]
            spi: Seasons Permanent Integrals
            si: Seasons integrals
            cf: Seasons cyclic fractions
            afi: Season Active Fraction
            warn: Warning flags

        :param : Time series as pandas.Series object
        """
        self.err = False
        self.warn = None

        self.sd = sd  # Start date - MBD
        self.ed = ed  # End date - MED
        self.mml = self.__time_delta(self.sd, self.ed)# Cycle length in days
        self.td = self.mml * 0.20  # time delta
        self.mms_b = ts.loc[sd - self.td:ed + self.td]  # buffered time series #TODO verify possible referencing
        self.mms = self.mms_b.loc[sd:ed]  # minimum minimum time series
        self.posix_time = self.mms.index.asi8 // 10 ** 9

        #self.stb = self.__integral(self.mms)  # Standing biomass (minimum minimum integral) [mi] [VOX x cycle]
        try:
            self.stb = _integral(self.mms.values)  # Standing biomass (minimum minimum integral) [mi] [VOX x cycle]
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! error in the integral calculation')
            return

        #self.mp = self.__min_min_line(self.mms)  # minimum minimum permanent (MPI minimum permanent Integral)
        try:
            self.mp = pd.Series(_min_min_line(self.mms.index.asi8.copy(), self.mms.values.copy()), self.mms.index)# minimum minimum permanent (MPI minimum permanent Integral)
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Error in interpolated line between two min')
            return

        #self.mpi = self.__integral(self.mp)  # minimum minimum permanent integral
        try:
            self.mpi = _integral(self.mp.values)  # Standing biomass (minimum minimum integral) [mi] [VOX x cycle]
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! error in the integral calculation')
            return

        #self.vox = self.__difference(self.mms, self.mp)  # Values between two min subtracted the permanent integral
        try:
            self.vox = pd.Series(_difference(self.mms.values, self.mp.values), self.mms.index)# Values between two min subtracted the permanent integral
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! difference between two time series')
            return

        self.vox_i = self.__integral(self.vox.values)

        #self.cbc = self.__barycenter()  # cycle barycenter / ex season barycenter
        try:
            self.cbc = _barycenter(self.posix_time, self.vox.values.copy())
        except(RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Barycenter calculation went wrong in reference')
            return

        if not self.cbc > 0:
            self.err = True
            logger.debug('Warning! Barycenter has a negative value')
            return

        self.cbcd = self.__to_gregorian_date(self.cbc)

        #self.csd = self.__cycle_deviation_standard()  # cycle deviation standard / Season deviation standard
        try:
            self.csd = _cycle_deviation_standard(self.cbc, self.posix_time, self.vox.values, self.vox_i)
        except ValueError:
            self.err = True
            logger.debug('Warning! Season deviation standard failed')
            return

        self.csdd = self.__to_gregorian(self.csd)  # cycle deviation standard in days /Season deviation standard in days
        self.max_idx = self.__max(self.mms)# date of maximum
        self.ref_yr = self.cbcd.year  # reference yr

        self.sfs = None
        self.mas = None
        self.unx_sbc = None

        self.sb = None  # Season beginning
        self.se = None  # Season end
        self.sbd = None  # Season beginning dates expressed as a date
        self.sed = None  # Season end dates expressed as date

        self.sl = None  # Season lengths in days
        self.spi = None  # Season Permanent Integrals
        self.si = None  # Season integrals
        self.cf = None  # Season cyclic fractions

        self.afi = None  # Season Active Fraction

        self.warn = None  # Warning flags

    def __time_delta(self, dt1, dt2):
        """Minimum minimum length expressed in delta time
           dt1: first date
           dt2: second date
        """
        try:
            return dt2 - dt1
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Minimum minimum length error')
            return None

    def __integral(self, ts):
        """Return the integral of a time series"""
        try:
            return ts.sum()
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! error in the integral calculation')
            return None

    def __min_min_line(self, ts):
        """Interpolated line between two min and give back a time series"""
        try:
            pf = ts.copy()
            pf[1:-1] = np.nan
            return pf.interpolate()
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Error in interpolated line between two min')
            return None

    def __difference(self, crv_1, crv_2):
        """Return the differences between two time series"""
        try:
            if crv_2.sum() > 0:
                out = crv_1 - crv_2
            else:
                out = crv_1 + crv_2
            return out
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! difference between two time series')
            return None

    def __to_gregorian_date(self, value):
        """Convert to pandas date format"""
        try:
            if value is not None:
                return pd.to_datetime(value, unit='s')
            else:
                raise ValueError('date value is null')
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Datetime conversion went wrong')
            return None

    def __to_gregorian(self, value):
        try:
            return pd.Timedelta(value, unit='s')
        except (RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Datetime conversion went wrong')
            return None

    def __max(self, ts):
        try:
            return ts.idxmax()
        except(RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Maximum research went wrong')
            return None

    def __barycenter(self):
        """Barycenter"""
        cbc = 0
        try:
            self.posix_time = self.vox.index.asi8 // 10**9
            cbc = (self.posix_time * self.vox).sum() / self.vox_i
        except(RuntimeError, Exception, ValueError):
            self.err = True
            logger.debug('Warning! Barycenter calculation went wrong in reference')
            return None

        if cbc > 0:
            return cbc
        else:
            self.err = True
            logger.debug('Warning! Barycenter has a negative value')
            return None

    def __cycle_deviation_standard(self):
        """Season deviation standard"""
        try:
            if self.cbc is not None:
                sup = (np.square(self.posix_time) * self.vox).sum() / self.vox_i
                inf = np.square(self.cbc)
                if sup >= inf:
                    return np.sqrt(sup - inf)
                else:
                    self.err = True
                    raise ValueError
            else:
                return None
        except ValueError:
            self.err = True
            logger.debug('Warning! Season deviation standard failed')
            return None


def _difference(crv_1, crv_2):
    """Return the differences between two time series"""

    if crv_2.sum() > 0:
        out = crv_1 - crv_2
    else:
        out = crv_1 + crv_2
    return out


@jit(nopython=True, cache=True)
def _integral(ts):
        """Return the integral of a time series"""
        return ts.sum()


@jit(nopython=True, cache=True)
def _barycenter(index, vox):
    """Barycenter"""
    cbc = (index * vox).sum() / vox.sum()
    return cbc


@jit(nopython=True, cache=True)
def _min_min_line(x, y):
    m = (y[-1] - y[0]) / (x[-1] - x[0])
    c = y[0] - m * x[0]
    y[1:-1] = m*x[1:-1]+c
    return y


@jit(nopython=True, cache=True)
def _cycle_deviation_standard(cbc, posix_time, vox, vox_i):
    """Season deviation standard"""
    if cbc is not None:
        sup = (np.square(posix_time) * vox).sum() / vox_i
        inf = np.square(cbc)
        if sup >= inf:
            return np.sqrt(sup - inf)
        else:
            return 0
    else:
        return 0

#
# from numba.core.types import uint8, uint64, float64, Boolean
# from numba.experimental import jitclass
#
# spec = [
#     ('err', Boolean),
#     ('warn', uint8),
#     ('sd', uint64),
#     ('ed', uint64),
#     ('mm_v', float64[:]),
#     ('mm_i', uint64[:]),
#     ('mml', uint64)
#
# ]
#
#
# @jitclass(spec)
# class SingularCycle(object):
#
#     def __init__(self, ts_v, ts_i, sd_i, ed_i):
#         """
#         Rappresent a singular cycle defined as the curve between two minima
#
#         Attributes:
#             mms: minimum minimum time series
#             mms_b : minimum minimum time series buffered by timdelta 2/3
#             sd: Start date - MBD
#             ed: End date - MED
#             mml: Cycle lenght in days
#             td: Time delta
#             sb: Standing biomas
#             mpf: permanent fration
#             mpi: permanent fration
#             vox: Values between two minima substracted the permanet fraction
#             voxi: integral
#             cbc: cycle baricenter / ex season baricenter
#             csd: cycle deviation standard / Season deviation standard
#             cdsdcycle: deviation standard in days /Season deviation standard in days
#             max_idx: date of maximum
#             ref_yr: reference yr
#
#             sb: Seasons beginning dates [Posix ns]
#             se:Seasons end dates [Posix ns]
#             sl:Seasons lengths dates [ns]
#             spi: Seasons Permanent Integrals
#             si: Seasons integrals
#             cf: Seasons cyclic fractions
#             afi: Season Active Fraction
#             warn: Warning flags
#
#         :param : Time series as pandas.Series object
#         """
#
#         self.err = False
#         self.warn = None
#
#         self.sd = sd_i  # Start date - MBD
#         self.ed = ed_i  # End date - MED
#
#         self.mm_v = ts_v[sd_i:ed_i]
#         self.mm_i = ts_i[sd_i:ed_i]
#
#         self.mml = self.__time_delta(self.sd, self.ed)  # Cycle length in days

    #     self.td = self.mml * 0.33  # time delta
    #     self.mms_b = ts.loc[sd - self.td:ed + self.td]  # buffered time series #TODO verify possible referencing
    #       # minimum minimum time series
    #     self.posix_time = self.mms.index.asi8 // 10 ** 9
    #
    #     #self.stb = self.__integral(self.mms)  # Standing biomass (minimum minimum integral) [mi] [VOX x cycle]
    #     try:
    #         self.stb = _integral(self.mms.values)  # Standing biomass (minimum minimum integral) [mi] [VOX x cycle]
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! error in the integral calculation')
    #         return
    #
    #     #self.mp = self.__min_min_line(self.mms)  # minimum minimum permanent (MPI minimum permanent Integral)
    #     try:
    #         self.mp = pd.Series(_min_min_line(self.mms.index.asi8.copy(), self.mms.values.copy()), self.mms.index)# minimum minimum permanent (MPI minimum permanent Integral)
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Error in interpolated line between two min')
    #         return
    #
    #     #self.mpi = self.__integral(self.mp)  # minimum minimum permanent integral
    #     try:
    #         self.mpi = _integral(self.mp.values)  # Standing biomass (minimum minimum integral) [mi] [VOX x cycle]
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! error in the integral calculation')
    #         return
    #
    #     #self.vox = self.__difference(self.mms, self.mp)  # Values between two min subtracted the permanent integral
    #     try:
    #         self.vox = pd.Series(_difference(self.mms.values, self.mp.values), self.mms.index)# Values between two min subtracted the permanent integral
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! difference between two time series')
    #         return
    #
    #     self.vox_i = self.__integral(self.vox.values)
    #
    #     #self.cbc = self.__barycenter()  # cycle barycenter / ex season barycenter
    #     try:
    #         self.cbc = _barycenter(self.posix_time, self.vox.values.copy())
    #     except(RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Barycenter calculation went wrong in reference')
    #         return
    #
    #     if not self.cbc > 0:
    #         self.err = True
    #         logger.debug('Warning! Barycenter has a negative value')
    #         return
    #
    #     self.cbcd = self.__to_gregorian_date(self.cbc)
    #
    #     #self.csd = self.__cycle_deviation_standard()  # cycle deviation standard / Season deviation standard
    #     try:
    #         self.csd = _cycle_deviation_standard(self.cbc, self.posix_time, self.vox.values, self.vox_i)
    #     except ValueError:
    #         self.err = True
    #         logger.debug('Warning! Season deviation standard failed')
    #         return
    #
    #     self.csdd = self.__to_gregorian(self.csd)  # cycle deviation standard in days /Season deviation standard in days
    #     self.max_idx = self.__max(self.mms)# date of maximum
    #     self.ref_yr = self.cbcd.year  # reference yr
    #
    #     self.sfs = None
    #     self.mas = None
    #     self.unx_sbc = None
    #
    #     self.sb = None  # Season beginning
    #     self.se = None  # Season end
    #     self.sbd = None  # Season beginning dates expressed as a date
    #     self.sed = None  # Season end dates expressed as date
    #
    #     self.sl = None  # Season lengths in days
    #     self.spi = None  # Season Permanent Integrals
    #     self.si = None  # Season integrals
    #     self.cf = None  # Season cyclic fractions
    #
    #     self.afi = None  # Season Active Fraction
    #
    #     self.warn = None  # Warning flags
    #
    # def __time_delta(self, dt1, dt2):
    #     """Minimum minimum length expressed in delta time
    #        dt1: first date
    #        dt2: second date
    #     """
    #     try:
    #         return dt2 - dt1
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Minimum minimum length error')
    #         return None
    #
    # def __integral(self, ts):
    #     """Return the integral of a time series"""
    #     try:
    #         return ts.sum()
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! error in the integral calculation')
    #         return None
    #
    # def __min_min_line(self, ts):
    #     """Interpolated line between two min and give back a time series"""
    #     try:
    #         pf = ts.copy()
    #         pf[1:-1] = np.nan
    #         return pf.interpolate()
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Error in interpolated line between two min')
    #         return None
    #
    # def __difference(self, crv_1, crv_2):
    #     """Return the differences between two time series"""
    #     try:
    #         if crv_2.sum() > 0:
    #             out = crv_1 - crv_2
    #         else:
    #             out = crv_1 + crv_2
    #         return out
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! difference between two time series')
    #         return None
    #
    # def __to_gregorian_date(self, value):
    #     """Convert to pandas date format"""
    #     try:
    #         if value is not None:
    #             return pd.to_datetime(value, unit='s')
    #         else:
    #             raise ValueError('date value is null')
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Datetime conversion went wrong')
    #         return None
    #
    # def __to_gregorian(self, value):
    #     try:
    #         return pd.Timedelta(value, unit='s')
    #     except (RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Datetime conversion went wrong')
    #         return None
    #
    # def __max(self, ts):
    #     try:
    #         return ts.idxmax()
    #     except(RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Maximum research went wrong')
    #         return None
    #
    # def __barycenter(self):
    #     """Barycenter"""
    #     cbc = 0
    #     try:
    #         self.posix_time = self.vox.index.asi8 // 10**9
    #         cbc = (self.posix_time * self.vox).sum() / self.vox_i
    #     except(RuntimeError, Exception, ValueError):
    #         self.err = True
    #         logger.debug('Warning! Barycenter calculation went wrong in reference')
    #         return None
    #
    #     if cbc > 0:
    #         return cbc
    #     else:
    #         self.err = True
    #         logger.debug('Warning! Barycenter has a negative value')
    #         return None
    #
    # def __cycle_deviation_standard(self):
    #     """Season deviation standard"""
    #     try:
    #         if self.cbc is not None:
    #             sup = (np.square(self.posix_time) * self.vox).sum() / self.vox_i
    #             inf = np.square(self.cbc)
    #             if sup >= inf:
    #                 return np.sqrt(sup - inf)
    #             else:
    #                 self.err = True
    #                 raise ValueError
    #         else:
    #             return None
    #     except ValueError:
    #         self.err = True
    #         logger.debug('Warning! Season deviation standard failed')
    #         return None
