from collections.abc import Iterable

import numpy as np
import pandas as pd

from pandapower.timeseries.data_sources.frame_data import DFData


def add_new_element(prosumer, element, overwrite=False):
    """

    :param net:
    :type net:
    :param component:
    :type component:
    :param overwrite:
    :type overwrite:
    :return:
    :rtype:
    """
    element = element()
    name = element.name
    excl_list = ['time_series', 'appliances']

    if not overwrite and name in prosumer:
        # logger.info('%s is already in net. Try overwrite if you want to get a new entry' %name)
        return
    else:
        element_input = element.input
        if name not in prosumer and not name in excl_list:
            prosumer['comp_list'].append(element)
        prosumer.update({name: element_input})
        if isinstance(prosumer[name], list):
            prosumer[name] = pd.DataFrame(np.zeros(0, dtype=prosumer[name]), index=[])


def reshaping_profiles(profile, resolution, norm=True):
    rest = len(profile) % resolution
    if rest:
        profile.extend(np.zeros(resolution - rest))
    if (max(np.abs(profile)) != 0) and norm:
        profile = np.array(profile) / max(profile)
    profile = np.mean(np.reshape(profile, (-1, resolution)), axis=1)
    return profile


def retrieve_result_columns(ts, result_columns=None, scaling=1., date_range=None):
    if isinstance(ts, DFData):
        if result_columns is None:
            data = ts.df.loc[:, 0].values * scaling
        elif not isinstance(ts.df.columns, pd.MultiIndex):
            if isinstance(result_columns, tuple):
                data = ts.df[list(result_columns)].values * scaling
            else:
                data = ts.df[result_columns].values * scaling
        else:
            data = ts.df.loc[:, 'result'][result_columns].values * scaling
    elif isinstance(ts, list) | isinstance(ts, np.ndarray):
        data = ts * scaling
    else:
        data = np.array([ts] * len(date_range))
    return data


def retrieve_time_series(prosumer, res, element, element_index, result_columns, del_input=True):
    ts = prosumer.time_series
    ts_idx, ele_idx_pos = check_data_frame(ts, 'element', 'element_index', element, element_index)
    found = np.zeros(len(element_index), dtype=bool)
    found[ele_idx_pos] = True
    for ts_i, ele_p in zip(ts_idx, ele_idx_pos):
        if len(np.shape(res)) == 1:
            res += retrieve_result_columns(ts.loc[int(ts_i)].data_source, result_columns)
        else:
            res[ele_p, :] += retrieve_result_columns(ts.loc[int(ts_i)].data_source, result_columns)
    if del_input:
        prosumer['time_series'].drop(ts_idx, inplace=True)
    return (found, res)


def aggregate_time_series(prosumer, res, obj, del_input=True, assigned_object_name='assigned_object'):
    sh_res = np.shape(res)
    for (el_idx, ass_ele) in enumerate(getattr(obj, assigned_object_name)):
        for ass_e, ass_i in zip(ass_ele.element_name, ass_ele.element_index):
            res_ele = np.zeros([len(ass_i), sh_res[1], sh_res[2]])
            found, agg_data = retrieve_time_series(prosumer, res_ele,
                                                   ass_e, ass_i, obj.result_columns, del_input)
            if not all(found):
                raise (ValueError('Not all of the elements where found. Following elements could not be found:'
                                  ' %s, %s '
                                  % (ass_e, np.array(ass_i)[~found])))
            res[el_idx, :] += agg_data.sum(axis=0)

    # df_idx: position in simple_char, die household zugeordnet sind
    # ele_idx_pos: position in element_index und wie sie df_idx zugeordnet sind
    # ts_idx: time_series indices, die zu df_idx gehören
    # df_idx_pos: postion in df_idx und wie sie zu ts_idx zugeordnet sind


def check_data_frame(df, df_element_column, df_element_index, assignee_element, assignee_index):
    # TODO: Needs to be checked again!
    pos_ele = np.where(assignee_element == df[df_element_column].values[:, np.newaxis])[0]
    rel_idx = df[df_element_index].values[pos_ele]
    rel_df_idx = df[df_element_index].index.values[pos_ele]
    df_pos, as_idx = np.where(rel_idx[:, np.newaxis] == assignee_index)
    df_idx = np.array(rel_df_idx)[df_pos].tolist()
    return df_idx, as_idx


def retrieve_sink_results_microscope(system, element_name, system_elements=None):
    if system_elements is None:
        sinks = system.system.sinks
    else:
        sinks = system_elements
    for sink in sinks:
        if element_name in sink.input.name:
            return sink.input.model_p_tau


def retrieve_source_results_microscope(system, element_name, system_elements=None):
    if system_elements is None:
        sources = system.system.sources
    else:
        sources = system_elements
    for source in sources:
        if element_name in source.output.name:
            return source.output.model_p_tau


def retrieve_storage_results_microscope(system, element_name):
    stores = system.system.storages
    ch = retrieve_source_results_microscope(system, element_name, stores)
    disch = retrieve_sink_results_microscope(system, element_name, stores)
    res = ch - disch
    return res


def phase_split(p, q, phase):
    res = dict()
    for i in range(3):
        res['p_L%s' % (i + 1)] = np.zeros(len(p))
        res['q_L%s' % (i + 1)] = np.zeros(len(q))
    if phase in ['L1', 'L2', 'L3']:
        res['p_%s' % phase] += p
        res['q_%s' % phase] += q
    elif (phase is None) or ('/' in phase):
        if phase is None:
            sp = ['L1', 'L2', 'L3']
            length = 3
        else:
            sp = phase.split('/')
            length = len(sp)
        for ph in sp:
            res['p_%s' % ph] += p / length
            res['q_%s' % ph] += q / length
    return res['p_L1'], res['p_L2'], res['p_L3'], res['q_L1'], res['q_L2'], res['q_L3']


def load_library_entry(prosumer, key, subkey, index, column=None):
    library = prosumer.library[key][subkey]
    if column is not None:
        if (index in library.index) and (column in library.columns):
            return library.at[index, column]
        else:
            raise UserWarning("Unknown library entry of index %s and column %s" % (index, column))
    else:
        if index in library:
            return library[index]
        else:
            raise UserWarning("Unknown library entry of index %s" % index)