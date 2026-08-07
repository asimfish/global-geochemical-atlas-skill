
===== PURPOSE =================================================================

This document describes the format of water quality data provided as
*.csv files by the GEMS/Water Data Center through the UNEP GEMS/Water Global 
Freshwater Quality Archive published on Zenodo. 

Be advised that this data delivery includes only data under our OPEN 
policy, as outlined in the section below on data policy. The data may
be used for all purposes, conforming with Creative Commons License
CC-BY 4.0.

For non-commercial purposes, additional data under the LIMITED data policy 
is available on the GEMStat data portal at 
https://portal.gemstat.org/applications/
or via custom e-mail request to gwdc@bafg.de.

Sample Times of 12:00 or 00:00 are default values for cases, when no Sample 
Time was reported by the data provider.



===== DATA DELIVERED ==========================================================

The data delivery consists of a Microsoft-Excel-file (parameter_request.xls)
containing a number of worksheets:
    
    1) A worksheet with station metadata (named Station_Metadata), containing 
       details on the stations that had data available for the specific request.

    2) A worksheet with parameter metadata (named Parameter_Metadata),  
       containing a description of the requested water quality parameters.
    
    3) A worksheet with analysis methods metadata (named Methods_Metadata), 
       containing a description of the methods used for analysis of the water 
       samples.
    
    4) A variable number of worksheets or csv-Files, containing the actual
       requested water quality sample results, either in a bulk ur split into
       separate chunks.



===== DATA POLICY =============================================================

GEMStat offers three levels of data policy, from which data suppliers may
choose the most applicable one for their data:

    1) OPEN       - raw data is publicly available and can be requested by 
	                everyone. This policy corresponds to the Creative Commons
					license CC BY 4.0.
					
	2) LIMITED    - raw data is shared upon written request to gwdc@bafg.de 
	                for non-commercial research only. For any other purpose, 
					only metadata and yearly aggregates at country level can be
				    requested. This license corresponds to the Creative Commons
					license CC BY-NC 4.0.
					
	3) RESTRICTED - raw data is not shared, even if they are visible in the data
	                portal. Its use is limited to statistical aggregates and
					UN assessments.
					

===== DATA FORMAT =============================================================

The station metadata table has the following entries:

    GEMS Station Number             - GEMStat internal station number.
    
    Local Station Number            - Station number according to the local 
                                      observation network nomenclature (if 
                                      available).
    
    Country Name                    - Name of country the station is located 
                                      in.
                                      
    Water Type                      - Type of water body, that is monitored by
                                      the station.
                                      
    Station Identifier              - Name of station.
    
    Station Narrative               - Description of stations location and  
                                      special conditions.
                                      
    Water Body Name                 - Name of the water body, where the  station 
                                      is located at, based on approved water 
                                      body names according to the US National 
                                      Geospatial Intelligence Agency 
                                      (http://geonames.nga.mil).
                                      
    Main Basin                      - Name of major river basin, that contains  
                                      the station, based on the Transboundary 
                                      Freshwater Dispute Database
                                      (https://transboundarywaters.science.oregonstate.edu/)
                                      and own delineations based on the 
                                      HydroBASINS dataset 
                                      (https://www.hydrosheds.org/).
                                      
    Upstream Basin Area             - Watershed area upstream of the station (in
                                      square kilometers).
    
    Elevation                       - Mean elevation of water surface above sea
                                      level for surface waters or ground level 
                                      for groundwater stations (in meters).
                                      
    Monitoring Type                 - Type of monitoring activity.
                                      Possible entries: 
                                      Baseline - determination of natural freshwater 
                                                 qualities in the absence of  
                                                 significant direct human impact
                                      Trend    - determination of long-term trends
                                      Impact   - determination of short term impacts 
                                                 of potential sources on water 
                                                 quality
                                      Flux     - determination of the fluxes of 
                                                 toxic chemicals, nutrients, 
                                                 suspended solids and other 
                                                 pollutants from major river basins 
                                                 to the continent/ocean interfaces
    
    Date Station Opened             - Date when station was established.
                                      Format: YYYY-MM-DD
                                      
    Responsible Collection Agency   - Name of Agency responsible for the 
                                      collection of data.
                                      
    Latitude                        - Cartesian y-Coordinates in WGS84.
    
    Longitude                       - Cartesian x-Coordinates in WGS84.
    
    River Width                     - Width of river (in meters) at the station
                                      during average discharge conditions.

    Discharge                       - Average river discharge (in cubic meters 
                                      per second) at the station based on 3-5 
                                      years of data.
    
    Max. Depth                      - Maximum depth (in meters) of lake or 
                                      reservoir.
    
    Lake Area                       - Area (in square kilometers) of lake or 
                                      reservoir.

    Lake Volume                     - Volume (in cubic kilometers) of lake or 
                                      reservoir.

    Average Retention               - Retention time (in years) of water in 
                                      lake or reservoir.

    Area of Aquifer                 - Area (in square kilometers) of aquifer.

    Depth of Impermeable Lining     - Depth (in meters) of the well casing (from 
                                      the earth surface to the top of the well 
                                      screen).
    
    Production Zone                 - Thickness (in meters) of the layer, 
                                      through which water can enter the well 
                                      (from the top of the well screen to the 
                                      bottom of the well).
    
    Mean Abstraction Rate           - Rate (in cubic meters per day) of water 
                                      abstraction from the well.
    
    Mean Abstraction Level          - Water level (in meters) inside the well  
                                      above mean sea level during a period of 
                                      normal abstraction. 

-------------------------------------------------------------------------------

The parameter metadata table has the following entries:

    Parameter Code                  - Code of water quality parameter and 
                                      fraction that has been sampled.

    Parameter Name                  - General name of water quality parameter.
    
    Parameter Long Name             - Complete Name of water quality parameter 
                                      and fraction.
    
    Parameter Group                 - Hierarchical group that the water
                                      quality parameter is associated with.
    
    EC Number                       - Unique seven-digit identifier of the 
                                      chemical substance, as assigned by the 
                                      European Commission.
    
    CAS Number                      - Unique identifier for the chemical 
                                      substance, as assigned by Chemical 
                                      Abstracts Service (CAS) to every 
                                      chemical substance described in the open 
                                      scientific literature.
    
    ChEBI Number                    - Unique identifier for the chemical 
                                      substance, as provided by the Chemical 
                                      Entities of Biological Interest (ChEBI) 
                                      dictionary.
    
    Parameter Description           - A description of the water quality 
                                      parameter. 
                                      (!!! Be advised: Some  special characters
                                      - e.g. '°' - have been corrupted during 
                                      encoding !!!)

-------------------------------------------------------------------------------

The methods metadata table has the following entries:

    Parameter Code                  - Code of water quality parameter and 
                                      fraction that has been sampled.
    
    Analysis Method Code            - Code of analysis method that was employed
                                      to get the reported value of the water 
                                      quality parameter.
    
    Unit                            - Reporting Unit of the water quality values
                                      determined by the given method.
    
    Parameter Long Name             - Complete Name of water quality parameter 
                                      and fraction.
                                      
    Method Name                     - Full name of analysis methodthat was 
                                      employed to get the reported value of the 
                                      water quality parameter.
    
    Method Type                     - Type of analysis method.

    Method Number                   - Number of analysis method in source 
                                      reference.

    Method Source                   - Reference to national or international 
                                      source of analysis method.
    
    Method Description              - A description of the analysis method, as
                                      by the data provider. 
                                      (!!! Be advised: Some  special characters
                                      - e.g. '°' - have been corrupted during 
                                      encoding !!!)
                                      
-------------------------------------------------------------------------------

Each of the water quality sample data tables have the following entries:

    GEMS Station Number             - GEMStat internal station number (see
                                      Station_Metadata table).
    
    Sample Date                     - Day on which the sample has been taken.
                                      Format: YYYY-MM-DD

    Sample Time                     - Time on which sample has been taken.
                                      The times are local times of the 
                                      respective monitoring location.
                                      Format: HH:mm (24-hour clock) 
                                      Default: 00:00 if not reported.
                                      
    Depth                           - Depth (in meters) below water surface,  
                                      from which sample has been taken.

    Parameter Code                  - Code of water quality parameter that has 
                                      been sampled (see Parameter_Metadata 
                                      table).

    Analysis Method Code            - Code of analysis method used for 
                                      determination of given water quality 
                                      parameter (see Methods_Metadata table).
                                      
    Value Flags                     - Quality flags for analysis result.
                                      Possible entries: 
                                        <       - below quantification limit
                                        >       - above quantification limit
                                        ~       - estimated value

    Value                           - Analysis result of given sample.
                                      
    Unit                            - Unit of analysis result.
                                      
    Data Quality                    - Rating of the Analysis result regarding
                                      its plausibility:
                                        Good            Confirmed suspected 
                                                        values.
                                        Fair            Default data quality for 
                                                        accepted values.
                                        Pending review  Values have exceeded pre-
                                                        defined technical limits 
                                                        and are thus pending 
                                                        review for confirmation.
                                        Estimated       The value has been 
                                                        reported as estimated.
                                        Suspect         Values have exceeded pre-
                                                        defined technical limits 
                                                        and have been reviewed 
                                                        as suspect.
                                        Contamination   A sample contamination 
                                                        has been reported for 
                                                        this value.
                                        Unknown         No detailed information 
                                                        on data quality available.
                                                        Treat as 'Fair' quality.
    Integrated Value                - Indicates, whether the values vere 
                                      integrated (i.e. averaged) over one of the 
                                      given domains:
                                        Horizontal Integration        (i.e. width)
                                        Time Integration
                                        Vertical Integration          (i.e. depth)
    
    Remark                          - Sample Remark as given by data provider
                                      
    License Information             - Link to data license of data provider. 
                                      (where applicable).