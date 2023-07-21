# Copyright 2022 RTDIP
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from jinja2 import Template
import datetime
from datetime import datetime, time

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

def _is_date_format(dt, format):
    try:
        return datetime.strptime(dt , format)
    except Exception:
        return False

def _parse_date(dt, is_end_date=False, exclude_date_format=False):   
    if isinstance(dt, datetime):
        if dt.time() == time.min:
            if dt.tzinfo is not None:
                dt = datetime.strftime(dt, "%Y-%m-%d%z")
            else:
                dt = dt.date()
        else:
            dt = datetime.strftime(dt, TIMESTAMP_FORMAT)
    dt = str(dt)

    if _is_date_format(dt, "%Y-%m-%d") and exclude_date_format == False:
        _time = "T23:59:59" if is_end_date == True else "T00:00:00"
        return dt + _time + "+00:00"
    elif _is_date_format(dt, "%Y-%m-%dT%H:%M:%S"):
        return dt + "+00:00"
    elif _is_date_format(dt, TIMESTAMP_FORMAT):
        return dt
    elif _is_date_format(dt, "%Y-%m-%d%z"):
        _time = "T23:59:59" if is_end_date == True else "T00:00:00"
        dt = dt[0:10] + _time + dt[10:]
        return dt
    else: 
        msg = f"Inputted timestamp: '{dt}', is not in the correct format."
        if exclude_date_format == True:
            msg += " List of timestamps must be in datetime format."
        raise ValueError(msg)
        
def _parse_dates(parameters_dict):
    if "start_date" in parameters_dict:
        parameters_dict["start_date"] = _parse_date(parameters_dict["start_date"])
        sample_dt = parameters_dict["start_date"]
    if "end_date" in parameters_dict:
        parameters_dict["end_date"] = _parse_date(parameters_dict["end_date"], True)
    if "timestamps" in parameters_dict:
        parsed_timestamp = [_parse_date(dt, is_end_date=False, exclude_date_format=True) for dt in parameters_dict["timestamps"]]
        parameters_dict["timestamps"] = parsed_timestamp
        sample_dt = parsed_timestamp[0]

    parameters_dict["time_zone"] = datetime.strptime(sample_dt, TIMESTAMP_FORMAT).strftime("%z")
    
    return parameters_dict

def _raw_query(parameters_dict: dict) -> str:

    raw_query = (
        "SELECT from_utc_timestamp(EventTime, \"{{ time_zone }}\") as EventTime, TagName, Status, Value FROM "
        "`{{ business_unit }}`.`sensors`.`{{ asset }}_{{ data_security_level }}_events_{{ data_type }}` "
        "WHERE EventDate BETWEEN to_date(to_timestamp(\"{{ start_date }}\")) AND to_date(to_timestamp(\"{{ end_date }}\")) AND EventTime BETWEEN to_timestamp(\"{{ start_date }}\") AND to_timestamp(\"{{ end_date }}\") AND TagName in ('{{ tag_names | join('\\', \\'') }}') "
        "{% if include_bad_data is defined and include_bad_data == false %}"
        "AND Status = 'Good'"
        "{% endif %}"
        "ORDER BY EventTime"
    )

    raw_parameters = {
        "business_unit": parameters_dict['business_unit'].lower(),
        "region": parameters_dict['region'].lower(),
        "asset": parameters_dict['asset'].lower(),
        "data_security_level": parameters_dict['data_security_level'].lower(),
        "data_type": parameters_dict['data_type'].lower(),
        "start_date": parameters_dict['start_date'],
        "end_date": parameters_dict['end_date'],
        "tag_names": list(dict.fromkeys(parameters_dict['tag_names'])),
        "include_bad_data": parameters_dict['include_bad_data'],
        "time_zone": parameters_dict["time_zone"]
    }

    sql_template = Template(raw_query)
    return sql_template.render(raw_parameters)

def _sample_query(parameters_dict: dict) -> tuple:

    sample_query = (
        "WITH raw_events AS (SELECT from_utc_timestamp(EventTime, \"{{ time_zone }}\") as EventTime, TagName, Status, Value FROM "
         "`{{ business_unit }}`.`sensors`.`{{ asset }}_{{ data_security_level }}_events_{{ data_type }}` "
        "WHERE EventDate BETWEEN to_date(to_timestamp(\"{{ start_date }}\")) AND to_date(to_timestamp(\"{{ end_date }}\")) AND EventTime BETWEEN to_timestamp(\"{{ start_date }}\") AND to_timestamp(\"{{ end_date }}\") AND TagName in ('{{ tag_names | join('\\', \\'') }}') "
        "{% if include_bad_data is defined and include_bad_data == false %} AND Status = 'Good' {% endif %}) "
        ",date_array AS (SELECT explode(sequence(from_utc_timestamp(to_timestamp(\"{{ start_date }}\"), \"{{ time_zone }}\"), from_utc_timestamp(to_timestamp(\"{{ end_date }}\"), \"{{ time_zone }}\"), INTERVAL '{{ sample_rate + ' ' + sample_unit }}')) AS timestamp_array, explode(array('{{ tag_names | join('\\', \\'') }}')) AS TagName) "
        ",window_buckets AS (SELECT timestamp_array AS window_start ,TagName ,LEAD(timestamp_array) OVER (ORDER BY timestamp_array) AS window_end FROM date_array) "
        ",project_resample_results AS (SELECT d.window_start ,d.window_end ,d.TagName ,FIRST(e.Value) OVER (PARTITION BY d.TagName, d.window_start ORDER BY e.EventTime ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS Value FROM window_buckets d INNER JOIN raw_events e ON e.EventTime >= d.window_start AND e.EventTime < d.window_end AND e.TagName = d.TagName) "
        "SELECT window_start AS EventTime ,TagName ,Value FROM project_resample_results GROUP BY window_start ,TagName ,Value ORDER BY EventTime, TagName "     
    )

    sample_parameters = {
        "business_unit": parameters_dict['business_unit'].lower(),
        "region": parameters_dict['region'].lower(),
        "asset": parameters_dict['asset'].lower(),
        "data_security_level": parameters_dict['data_security_level'].lower(),
        "data_type": parameters_dict['data_type'].lower(),
        "start_date": parameters_dict['start_date'],
        "end_date": parameters_dict['end_date'],
        "tag_names": list(dict.fromkeys(parameters_dict['tag_names'])),
        "include_bad_data": parameters_dict['include_bad_data'],
        "sample_rate": parameters_dict['sample_rate'],
        "sample_unit": parameters_dict['sample_unit'],
        "agg_method": parameters_dict['agg_method'],
        "time_zone": parameters_dict["time_zone"]
    }

    sql_template = Template(sample_query)
    sql_query = sql_template.render(sample_parameters)
    return sql_query, sample_query, sample_parameters    

def _interpolation_query(parameters_dict: dict, sample_query: str, sample_parameters: dict) -> str:

    if parameters_dict["interpolation_method"] == "forward_fill":
        interpolation_method = 'last_value/UNBOUNDED PRECEDING/CURRENT ROW'

    if parameters_dict["interpolation_method"] == "backward_fill":
        interpolation_method = 'first_value/CURRENT ROW/UNBOUNDED FOLLOWING'

    interpolation_options = interpolation_method.split('/')

    interpolate_query = (
        f"WITH resample AS ({sample_query})"
        ",date_array AS (SELECT explode(sequence(from_utc_timestamp(to_timestamp(\"{{ start_date }}\"), \"{{ time_zone }}\"), from_utc_timestamp(to_timestamp(\"{{ end_date }}\"), \"{{ time_zone }}\"), INTERVAL '{{ sample_rate + ' ' + sample_unit }}')) AS EventTime, explode(array('{{ tag_names | join('\\', \\'') }}')) AS TagName) "
        "SELECT a.EventTime, a.TagName, {{ interpolation_options_0 }}(b.Value, true) OVER (PARTITION BY a.TagName ORDER BY a.EventTime ROWS BETWEEN {{ interpolation_options_1 }} AND {{ interpolation_options_2 }}) AS Value FROM date_array a "
        "LEFT OUTER JOIN resample b "
        "ON a.EventTime = b.EventTime AND a.TagName = b.TagName ORDER BY a.EventTime, a.TagName"    
    )
    
    interpolate_parameters = sample_parameters.copy()
    interpolate_parameters["interpolation_options_0"] = interpolation_options[0]
    interpolate_parameters["interpolation_options_1"] = interpolation_options[1]
    interpolate_parameters["interpolation_options_2"] = interpolation_options[2]

    sql_template = Template(interpolate_query)
    return sql_template.render(interpolate_parameters)

def _interpolation_at_time(parameters_dict: dict) -> str:
    timestamps_deduplicated = list(dict.fromkeys(parameters_dict['timestamps'])) #remove potential duplicates in tags
    parameters_dict["timestamps"] = timestamps_deduplicated.copy()
    parameters_dict["min_timestamp"] = min(timestamps_deduplicated)
    parameters_dict["max_timestamp"] = max(timestamps_deduplicated)

    interpolate_at_time_query = (
        "WITH raw_events AS (SELECT * FROM `{{ business_unit }}`.`sensors`.`{{ asset }}_{{ data_security_level }}_events_{{ data_type }}` WHERE EventDate BETWEEN "
        "{% if timestamps is defined %} "
        "date_sub(to_date(to_timestamp(\"{{ min_timestamp }}\")), 1) AND date_add(to_date(to_timestamp(\"{{ max_timestamp }}\")), 1) "
        "{% endif %} AND TagName in ('{{ tag_names | join('\\', \\'') }}') "
        "{% if include_bad_data is defined and include_bad_data == false %} AND Status = 'Good' {% endif %}) "
        ", date_array AS (SELECT explode(array( "
        "{% for timestamp in timestamps -%} "
        "from_utc_timestamp(to_timestamp(\"{{timestamp}}\"), \"{{time_zone}}\") "
        "{% if not loop.last %} , {% endif %} {% endfor %} )) AS EventTime, "
        "explode(array('{{ tag_names | join('\\', \\'') }}')) AS TagName) "
        ", interpolation_events AS (SELECT coalesce(a.TagName, b.TagName) as TagName, coalesce(a.EventTime, b.EventTime) as EventTime, a.EventTime as Requested_EventTime, b.EventTime as Found_EventTime, b.Status, b.Value FROM date_array a FULL OUTER JOIN  raw_events b ON a.EventTime = b.EventTime AND a.TagName = b.TagName) "
        ", interpolation_calculations AS (SELECT *, lag(EventTime) OVER (PARTITION BY TagName ORDER BY EventTime) AS Previous_EventTime, lag(Value) OVER (PARTITION BY TagName ORDER BY EventTime) AS Previous_Value, lead(EventTime) OVER (PARTITION BY TagName ORDER BY EventTime) AS Next_EventTime, lead(Value) OVER (PARTITION BY TagName ORDER BY EventTime) AS Next_Value, "
        "CASE WHEN Requested_EventTime = Found_EventTime THEN Value WHEN Next_EventTime IS NULL THEN Previous_Value WHEN Previous_EventTime IS NULL and Next_EventTime IS NULL THEN NULL "
        "ELSE Previous_Value + ((Next_Value - Previous_Value) * ((unix_timestamp(EventTime) - unix_timestamp(Previous_EventTime)) / (unix_timestamp(Next_EventTime) - unix_timestamp(Previous_EventTime)))) END AS Interpolated_Value FROM interpolation_events) "
        "SELECT TagName, EventTime, Interpolated_Value as Value FROM interpolation_calculations WHERE EventTime in ( "
        "{% for timestamp in timestamps -%} "
        "from_utc_timestamp(to_timestamp(\"{{timestamp}}\"), \"{{time_zone}}\") "
        "{% if not loop.last %} , {% endif %} {% endfor %}) "  
    )
    
    interpolation_at_time_parameters = {
        "business_unit": parameters_dict['business_unit'].lower(),
        "region": parameters_dict['region'].lower(),
        "asset": parameters_dict['asset'].lower(),
        "data_security_level": parameters_dict['data_security_level'].lower(),
        "data_type": parameters_dict['data_type'].lower(),
        "tag_names": list(dict.fromkeys(parameters_dict['tag_names'])),
        "timestamps": parameters_dict['timestamps'],
        "include_bad_data": parameters_dict["include_bad_data"],
        "time_zone": parameters_dict["time_zone"],
        "min_timestamp": parameters_dict["min_timestamp"],
        "max_timestamp": parameters_dict["max_timestamp"]
    }
    sql_template = Template(interpolate_at_time_query)
    return sql_template.render(interpolation_at_time_parameters)

def _metadata_query(parameters_dict: dict) -> str:
    
    metadata_query  = (
        "SELECT * FROM "
        "`{{ business_unit }}`.`sensors`.`{{ asset }}_{{ data_security_level }}_metadata` "
        "{% if tag_names is defined and tag_names|length > 0 %} "
        "WHERE TagName in ({{ tag_names | join('\\', \\'') }}) "
        "{% endif %}"
    )

    metadata_parameters = {
        "business_unit": parameters_dict['business_unit'].lower(),
        "region": parameters_dict['region'].lower(),
        "asset": parameters_dict['asset'].lower(),
        "data_security_level": parameters_dict['data_security_level'].lower(),
        "tag_names": list(dict.fromkeys(parameters_dict['tag_names']))
    }

    sql_template = Template(metadata_query)
    return sql_template.render(metadata_parameters)

def _query_builder(parameters_dict: dict, query_type: str) -> str:
    if "tag_names" not in parameters_dict:
        parameters_dict["tag_names"] = []
    tagnames_deduplicated = list(dict.fromkeys(parameters_dict['tag_names'])) #remove potential duplicates in tags
    parameters_dict["tag_names"] = tagnames_deduplicated.copy()

    if query_type == "metadata":
        return _metadata_query(parameters_dict)
    
    parameters_dict = _parse_dates(parameters_dict)
    
    if query_type == "interpolation_at_time":
        return _interpolation_at_time(parameters_dict)

    if query_type == "raw":
        return _raw_query(parameters_dict)
    
    if query_type == "resample":
        sample_prepared_query, sample_query, sample_parameters = _sample_query(parameters_dict)
        return sample_prepared_query
    
    if query_type == "interpolate":
        sample_prepared_query, sample_query, sample_parameters = _sample_query(parameters_dict)
        return _interpolation_query(parameters_dict, sample_query, sample_parameters)