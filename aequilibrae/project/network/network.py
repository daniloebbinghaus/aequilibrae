import math
from warnings import warn
from sqlite3 import Connection as sqlc
from typing import Dict
import numpy as np
import pandas as pd
import string
import shapely.wkb
from shapely.geometry import Polygon
from shapely.ops import unary_union
from aequilibrae.project.network import OSMDownloader
from aequilibrae.project.network.osm_builder import OSMBuilder
from aequilibrae.project.network.osm_utils.place_getter import placegetter
from aequilibrae.project.network.haversine import haversine
from aequilibrae.project.network.modes import Modes
from aequilibrae.project.network.link_types import LinkTypes
from aequilibrae.project.network.links import Links
from aequilibrae.project.network.nodes import Nodes
from aequilibrae.paths import Graph
from aequilibrae.parameters import Parameters
from aequilibrae import logger
from aequilibrae.project.project_creation import req_link_flds, req_node_flds, protected_fields


class Network:
    """
    Network class. Member of an AequilibraE Project
    """

    req_link_flds = req_link_flds
    req_node_flds = req_node_flds
    protected_fields = protected_fields
    link_types: LinkTypes = None

    def __init__(self, project) -> None:
        self.conn = project.conn  # type: sqlc
        self.source = project.source  # type: sqlc
        self.graphs = {}  # type: Dict[Graph]
        self.modes = Modes(self)
        self.link_types = LinkTypes(self)
        self.links = Links()
        self.nodes = Nodes()

    def skimmable_fields(self):
        """
        Returns a list of all fields that can be skimmed

        Returns:
            :obj:`list`: List of all fields that can be skimmed
        """
        curr = self.conn.cursor()
        curr.execute("PRAGMA table_info(links);")
        field_names = curr.fetchall()
        ignore_fields = ["ogc_fid", "geometry"] + self.req_link_flds

        skimmable = [
            "INT",
            "INTEGER",
            "TINYINT",
            "SMALLINT",
            "MEDIUMINT",
            "BIGINT",
            "UNSIGNED BIG INT",
            "INT2",
            "INT8",
            "REAL",
            "DOUBLE",
            "DOUBLE PRECISION",
            "FLOAT",
            "DECIMAL",
            "NUMERIC",
        ]
        all_fields = []

        for f in field_names:
            if f[1] in ignore_fields:
                continue
            for i in skimmable:
                if i in f[2].upper():
                    all_fields.append(f[1])
                    break

        all_fields.append("distance")
        real_fields = []
        for f in all_fields:
            if f[-2:] == "ab":
                if f[:-2] + "ba" in all_fields:
                    real_fields.append(f[:-3])
            elif f[-3:] != "_ba":
                real_fields.append(f)

        return real_fields

    def list_modes(self):
        """
        Returns a list of all the modes in this model

        Returns:
            :obj:`list`: List of all modes
        """
        curr = self.conn.cursor()
        curr.execute("""select mode_id from modes""")
        return [x[0] for x in curr.fetchall()]

    def create_from_osm(
        self,
        west: float = None,
        south: float = None,
        east: float = None,
        north: float = None,
        place_name: str = None,
        modes=["car", "transit", "bicycle", "walk"],
    ) -> None:
        """
        Downloads the network from Open-Street Maps

        Args:
            *west* (:obj:`float`, Optional): West most coordinate of the download bounding box

            *south* (:obj:`float`, Optional): South most coordinate of the download bounding box

            *east* (:obj:`float`, Optional): East most coordinate of the download bounding box

            *place_name* (:obj:`str`, Optional): If not downloading with East-West-North-South boundingbox, this is
            required

            *modes* (:obj:`list`, Optional): List of all modes to be downloaded. Defaults to the modes in the parameter
            file

            p = Project()
            p.new(nm)

        ::

            from aequilibrae import Project, Parameters
            p = Project()
            p.new('path/to/project')

            # We now choose a different overpass endpoint (say a deployment in your local network)
            par = Parameters()
            par.parameters['osm']['overpass_endpoint'] = "http://192.168.1.234:5678/api"

            # Because we have our own server, we can set a bigger area for download (in M2)
            par.parameters['osm']['max_query_area_size'] = 10000000000

            # And have no pause between successive queries
            par.parameters['osm']['sleeptime'] = 0

            # Save the parameters to disk
            par.write_back()

            # And do the import
            p.network.create_from_osm(place_name=my_beautiful_hometown)
            p.close()
        """

        if self.count_links() > 0:
            raise FileExistsError("You can only import an OSM network into a brand new model file")

        curr = self.conn.cursor()
        curr.execute("""ALTER TABLE links ADD COLUMN osm_id integer""")
        curr.execute("""ALTER TABLE nodes ADD COLUMN osm_id integer""")
        self.conn.commit()

        if isinstance(modes, (tuple, list)):
            modes = list(modes)
        elif isinstance(modes, str):
            modes = [modes]
        else:
            raise ValueError("'modes' needs to be string or list/tuple of string")

        if place_name is None:
            if min(east, west) < -180 or max(east, west) > 180 or min(north, south) < -90 or max(north, south) > 90:
                raise ValueError("Coordinates out of bounds")
            bbox = [west, south, east, north]
        else:
            bbox, report = placegetter(place_name)
            west, south, east, north = bbox
            if bbox is None:
                msg = f'We could not find a reference for place name "{place_name}"'
                warn(msg)
                logger.warning(msg)
                return
            for i in report:
                if "PLACE FOUND" in i:
                    logger.info(i)

        # Need to compute the size of the bounding box to not exceed it too much
        height = haversine((east + west) / 2, south, (east + west) / 2, north)
        width = haversine(east, (north + south) / 2, west, (north + south) / 2)
        area = height * width

        par = Parameters().parameters["osm"]
        max_query_area_size = par["max_query_area_size"]

        if area < max_query_area_size:
            polygons = [bbox]
        else:
            polygons = []
            parts = math.ceil(area / max_query_area_size)
            horizontal = math.ceil(math.sqrt(parts))
            vertical = math.ceil(parts / horizontal)
            dx = (east - west) / horizontal
            dy = (north - south) / vertical
            for i in range(horizontal):
                xmin = max(-180, west + i * dx)
                xmax = min(180, west + (i + 1) * dx)
                for j in range(vertical):
                    ymin = max(-90, south + j * dy)
                    ymax = min(90, south + (j + 1) * dy)
                    box = [xmin, ymin, xmax, ymax]
                    polygons.append(box)
        logger.info("Downloading data")
        self.downloader = OSMDownloader(polygons, modes)
        self.downloader.doWork()

        logger.info("Building Network")
        self.builder = OSMBuilder(self.downloader.json, self.source)
        self.builder.doWork()

        logger.info("Network built successfully")

    def create_from_gmns(self, link_file_path: str, node_file_path: str) -> None:
        """
            Documentation in progress...
        """

        p = Parameters()
        gmns_l_fields = p.parameters["network"]["gmns"]["link_fields"]
        gmns_n_fields = p.parameters["network"]["gmns"]["node_fields"]

        # Collecting GMNS fields names

        gmns_link_id_field = gmns_l_fields["link_id"]
        gmns_a_node_field = gmns_l_fields["a_node"]
        gmns_b_node_field = gmns_l_fields["b_node"]
        gmns_distance_field = gmns_l_fields["distance"]
        gmns_direction_field = gmns_l_fields["direction"]
        gmns_speed_field = gmns_l_fields["speed"]
        gmns_capacity_field = gmns_l_fields["capacity"]
        gmns_lanes_field = gmns_l_fields["lanes"]
        gmns_name_field = gmns_l_fields["name"]
        gmns_link_type_field = gmns_l_fields["link_type"]
        gmns_modes_field = gmns_l_fields["modes"]
        gmns_geometry_field = gmns_l_fields["geometry"]

        gmns_node_id_field = gmns_n_fields["node_id"]

        # Loading GMNS files

        gmns_links_df = pd.read_csv(link_file_path)
        gmns_nodes_df = pd.read_csv(node_file_path)

        # Checking if all required fields are in GMNS links and nodes files
        
        for field in p.parameters["network"]["gmns"]["required_node_fields"]:
            if field not in gmns_nodes_df.columns.to_list():
                raise ValueError(f"In GMNS nodes file: field '{field}' required, but not found.")

        for field in p.parameters["network"]["gmns"]["required_link_fields"]:
            if field not in gmns_links_df.columns.to_list():
                if field == "directed":
                    gmns_links_df[field] = False
                else:
                    raise ValueError(f"In GMNS links file: field '{field}' required, but not found.")

        if gmns_geometry_field not in gmns_links_df.columns.to_list():
            raise ValueError("To create an aequilibrae links table, a 'geometry' field must be provided. Geometry field not found in GMNS links file.")
        
        # Adding 'lanes_ab' and 'lanes_ba' fields to links table
        # Also, adding 'notes' field to AequilibraE links and nodes tables if not already added

        links_fields = self.links.fields().all_fields()

        for col in ["lanes_ab", "lanes_ba"]:
            if col not in links_fields:
                l_fields = self.links.fields()
                l_fields.add(col, description='Lanes', data_type="NUMERIC")
                l_fields.save()

        if 'notes' not in links_fields:
            l_fields = self.links.fields()
            l_fields.add('notes', description='More information about the link', data_type="TEXT")
            l_fields.save()

        nodes_fields = self.nodes.fields().all_fields()
        if 'notes' not in nodes_fields:
            n_fields = self.nodes.fields()
            n_fields.add('notes', description='More information about the node', data_type="TEXT")
            n_fields.save()

        # Creating distance field if it does not exist

        if gmns_distance_field not in gmns_links_df.columns.to_list():
            gmns_links_df[gmns_distance_field] = None

        # Getting list of two-way links
        
        df_count = gmns_links_df.groupby(["from_node_id", "to_node_id"], as_index=False).count()
        df_two_way_count = df_count[df_count.link_id >= 2]
        if df_two_way_count.shape[0] > 0:
            two_way_nodes = list(zip(df_two_way_count.from_node_id, df_two_way_count.to_node_id))

            two_way_df = gmns_links_df[gmns_links_df[["from_node_id", "to_node_id"]].apply(tuple, 1).isin(two_way_nodes)]
            two_way_links = two_way_df.sort_values('link_id').drop_duplicates(subset=["from_node_id", "to_node_id"], keep='last').link_id.to_list()

            gmns_links_df = gmns_links_df.sort_values('link_id').drop_duplicates(subset=["from_node_id", "to_node_id"], keep='last')
            gmns_links_df.reset_index(drop=True, inplace=True)

            two_way_indices = gmns_links_df.index[gmns_links_df.link_id.isin(two_way_links)].to_list()

        else:
            two_way_indices = []

        # Setting direction variable based on list of two-way links

        if gmns_direction_field not in gmns_links_df.columns.to_list():
            gmns_links_df[gmns_direction_field] = 1

        direction = gmns_links_df[gmns_direction_field].to_list()

        if two_way_indices != []:    
            for idx in two_way_indices:
                direction[idx] = 0

        ## Assuming direction from 'from_node_id' to 'to_node_id' (direction=1) in case there is no information about it
        
        for idx, i in enumerate(direction):
            if i not in [1, 0, -1]:
                direction[idx] = 1

        # Setting speeds, capacities and lanes based on direction list

        speed_ab = ['' for _ in range(len(gmns_links_df))]
        speed_ba = ['' for _ in range(len(gmns_links_df))]
        capacity_ab = ['' for _ in range(len(gmns_links_df))]
        capacity_ba = ['' for _ in range(len(gmns_links_df))]
        lanes_ab = ['' for _ in range(len(gmns_links_df))]
        lanes_ba = ['' for _ in range(len(gmns_links_df))]
        
        for idx, row in gmns_links_df.iterrows():
            if gmns_speed_field in gmns_links_df.columns.to_list():
                if direction[idx] == 1:
                    speed_ab[idx] = row[gmns_speed_field]
                elif direction[idx] == -1:
                    speed_ba[idx] = row[gmns_speed_field]
                else:
                    speed_ab[idx] = row[gmns_speed_field]
                    speed_ba[idx] = row[gmns_speed_field]
            
            if gmns_capacity_field in gmns_links_df.columns.to_list():
                if direction[idx] == 1:
                    capacity_ab[idx] = row[gmns_capacity_field]
                elif direction[idx] == -1:
                    capacity_ba[idx] = row[gmns_capacity_field]
                else:
                    capacity_ab[idx] = row[gmns_capacity_field]
                    capacity_ba[idx] = row[gmns_capacity_field]
            
            if gmns_lanes_field in gmns_links_df.columns.to_list():
                if direction[idx] == 1:
                    lanes_ab[idx] = row[gmns_lanes_field]
                elif direction[idx] == -1:
                    lanes_ba[idx] = row[gmns_lanes_field]
                else:
                    lanes_ab[idx] = row[gmns_lanes_field]
                    lanes_ba[idx] = row[gmns_lanes_field]

        # Getting information from some optinal GMNS fields

        if gmns_name_field in gmns_links_df.columns.to_list():
            name_list = gmns_links_df[gmns_name_field].to_list()
        else:
            name_list = ['' for _ in range(len(gmns_links_df))]

        # Setting link_type list
        # Setting link_type = 'unclassified' if there is no information about it in the GMNS links table

        if gmns_link_type_field not in gmns_links_df.columns.to_list():
            gmns_link_type_field = "link_type_name"
            if gmns_link_type_field not in gmns_links_df.columns.to_list():
                link_types_list = ['unclassified' for _ in range(len(gmns_links_df))]
            else:
                link_types_list = gmns_links_df[gmns_link_type_field].to_list()
        else:
            link_types_list = gmns_links_df[gmns_link_type_field].to_list()

        ## Adding link_types to model

        for lt_name in list(dict.fromkeys(link_types_list)):
            saved = False
            i = 0
            while not saved and i < len(lt_name):
                if lt_name[i].lower() not in list(self.link_types.all_types()):
                    link_types = self.link_types
                    new_type = link_types.new(lt_name[i].lower())
                    new_type.link_type = lt_name
                    new_type.save()
                    saved = True

                elif lt_name[i].upper() not in list(self.link_types.all_types()):
                    link_types = self.link_types
                    new_type = link_types.new(lt_name[i].upper())
                    new_type.link_type = lt_name
                    new_type.save()
                    saved = True
                i += 1

            if not saved:
                ascii_idx = 0
                while not saved:
                    try:
                        ascii_lt = string.ascii_letters[ascii_idx]
                    except:
                        raise ValueError("Error during creation of new link_type: all letters are currently in use.")

                    if ascii_lt not in list(self.link_types.all_types()):
                        link_types = self.link_types
                        new_type = link_types.new(ascii_lt)
                        new_type.link_type = lt_name
                        new_type.save()
                        saved = True

                    ascii_idx += 1

        # Creating modes list

        modes_list = ['' for _ in range(len(gmns_links_df))]

        gmns_modes = p.parameters["network"]["gmns"]["modes"]["gmns_users"]
        gmns_modes_list = [k for i in gmns_modes for k in i.keys()]

        if gmns_modes_field in gmns_links_df.columns.to_list():

            for idx, row in gmns_links_df.iterrows():
                if row[gmns_modes_field] in gmns_modes_list:
                    mode = row[gmns_modes_field]
                    modes_list[idx] = [x for x in gmns_modes if mode in x][0]['auto'][1]["letters"]

                    for letter in modes_list[idx]:
                        if letter not in self.list_modes():
                            modes = self.modes
                            new_mode = modes.new(letter)
                            new_mode.mode_name = [i[k][0]["description"] for i in gmns_modes for k in i.keys() if i[k][1]["letters"] == letter][0]
                            modes.add(new_mode)
                            new_mode.description = 'Mode from GMNS link table'
                            new_mode.save()
                    
        else:
            if gmns_link_type_field == "link_type_name" and gmns_link_type_field not in gmns_links_df.columns.to_list():
                raise ValueError("GMNS table does not have information about modes or link types.")

            bike_link_types = p.parameters["network"]["gmns"]["modes"]["bicycle"]["link_types"]
            car_link_types = p.parameters["network"]["gmns"]["modes"]["car"]["link_types"]
            transit_link_types = p.parameters["network"]["gmns"]["modes"]["transit"]["link_types"]
            walk_link_types = p.parameters["network"]["gmns"]["modes"]["walk"]["link_types"]
            for idx, row in gmns_links_df.iterrows():

                if row[gmns_link_type_field] in bike_link_types:
                    modes_list[idx] = "b"

                elif row[gmns_link_type_field] in car_link_types:
                    modes_list[idx] = "c"
                
                elif row[gmns_link_type_field] in transit_link_types:
                    modes_list[idx] = "t"

                elif row[gmns_link_type_field] in walk_link_types:
                    modes_list[idx] = "w"

        # Checking if there is information in the 'bike_facility' and 'ped_facility' optional fields

        gmns_bike_facilities = ['wcl', 'bikelane', 'cycletrack']
        gmns_ped_facilities = ['shoulder', 'sidewalk']
        if 'bike_facility' in gmns_links_df.columns.to_list():
            for idx, row in gmns_links_df.iterrows():
                if row.bike_facility in gmns_bike_facilities and "b" not in modes_list[idx]:
                    modes_list[idx] += "b"
        
        if 'ped_facility' in gmns_links_df.columns.to_list():
            for idx, row in gmns_links_df.iterrows():
                if row.ped_facility in gmns_ped_facilities and "w" not in modes_list[idx]:
                    modes_list[idx] += "w"

        # Creating dataframes for adding nodes and links information to AequilibraE model

        aeq_nodes_df = pd.DataFrame({
            'node_id': gmns_nodes_df[gmns_node_id_field],
            'is_centroid': 0,
            'x_coord': gmns_nodes_df.x_coord,
            'y_coord': gmns_nodes_df.y_coord,
            'notes': 'from GMNS file'
        })

        aeq_links_df = pd.DataFrame({
            'link_id': gmns_links_df[gmns_link_id_field],
            'a_node': gmns_links_df[gmns_a_node_field], 
            'b_node': gmns_links_df[gmns_b_node_field], 
            'direction': direction,
            'distance': gmns_links_df[gmns_distance_field],
            'modes': modes_list,
            'link_type': link_types_list,
            'name': name_list, 
            'speed_ab': speed_ab,
            'speed_ba': speed_ba,
            'capacity_ab': capacity_ab,
            'capacity_ba': capacity_ba,
            'geometry': gmns_links_df.geometry, 
            'lanes_ab': lanes_ab,
            'lanes_ba': lanes_ba,
            'notes': 'from GMNS file'
        })

        n_query = '''
            insert into nodes(node_id, is_centroid, geometry, notes) 
            values(?,?,MakePoint(?,?, 4326),?);
        '''
        n_params_list = []
        for _, row in aeq_nodes_df.iterrows():
            n_params_list.append([row.node_id, row.is_centroid, row.x_coord, row.y_coord, row.notes])

        self.conn.executemany(n_query, n_params_list)
        self.conn.commit()

        l_query = '''
            insert into links(link_id, a_node, b_node, direction, distance, modes, link_type, name, speed_ab, speed_ba, capacity_ab, capacity_ba, geometry, lanes_ab, lanes_ba, notes) 
            values(?,?,?,?,?,?,?,?,?,?,?,?,GeomFromTEXT(?,4326),?,?,?);
        '''
        l_params_list = []
        for _, row in aeq_links_df.iterrows():
            l_params_list.append([
                row.link_id,
                row.a_node,
                row.b_node,
                row.direction,
                row.distance,
                row.modes,
                row.link_type,
                row['name'],    
                row.speed_ab,
                row.speed_ba,
                row.capacity_ab,
                row.capacity_ba,
                row.geometry,
                row.lanes_ab,
                row.lanes_ba,
                row.notes
            ])
        
        self.conn.executemany(l_query, l_params_list)
        self.conn.commit()

        logger.info("Network built successfully")

    def build_graphs(self, fields: list = None, modes: list = None) -> None:
        """Builds graphs for all modes currently available in the model

        When called, it overwrites all graphs previously created and stored in the networks'
        dictionary of graphs

        Args:
            *fields* (:obj:`list`, optional): When working with very large graphs with large number of fields in the
                                              database, it may be useful to specify which fields to use
            *modes* (:obj:`list`, optional): When working with very large graphs with large number of fields in the
                                              database, it may be useful to generate only those we need

        To use the *fields* parameter, a minimalistic option is the following
        ::

            p = Project()
            p.open(nm)
            fields = ['distance']
            p.network.build_graphs(fields, modes = ['c', 'w'])

        """
        curr = self.conn.cursor()

        if fields is None:
            curr.execute("PRAGMA table_info(links);")
            field_names = curr.fetchall()

            ignore_fields = ["ogc_fid", "geometry"]
            all_fields = [f[1] for f in field_names if f[1] not in ignore_fields]
        else:
            fields.extend(["link_id", "a_node", "b_node", "direction", "modes"])
            all_fields = list(set(fields))

        if modes is None:
            modes = curr.execute("select mode_id from modes;").fetchall()
            modes = [m[0] for m in modes]
        elif isinstance(modes, str):
            modes = [modes]

        sql = f"select {','.join(all_fields)} from links"

        df = pd.read_sql(sql, self.conn).fillna(value=np.nan)
        valid_fields = list(df.select_dtypes(np.number).columns) + ["modes"]
        curr.execute("select node_id from nodes where is_centroid=1 order by node_id;")
        centroids = np.array([i[0] for i in curr.fetchall()], np.uint32)

        data = df[valid_fields]
        for m in modes:
            net = pd.DataFrame(data, copy=True)
            net.loc[~net.modes.str.contains(m), "b_node"] = net.loc[~net.modes.str.contains(m), "a_node"]
            g = Graph()
            g.mode = m
            g.network = net
            g.prepare_graph(centroids)
            g.set_blocked_centroid_flows(True)
            self.graphs[m] = g

    def set_time_field(self, time_field: str) -> None:
        """
        Set the time field for all graphs built in the model

        Args:
            *time_field* (:obj:`str`): Network field with travel time information
        """
        for m, g in self.graphs.items():  # type: str, Graph
            if time_field not in list(g.graph.columns):
                raise ValueError(f"{time_field} not available. Check if you have NULL values in the database")
            g.free_flow_time = time_field
            g.set_graph(time_field)
            self.graphs[m] = g

    def count_links(self) -> int:
        """
        Returns the number of links in the model

        Returns:
            :obj:`int`: Number of links
        """
        return self.__count_items("link_id", "links", "link_id>=0")

    def count_centroids(self) -> int:
        """
        Returns the number of centroids in the model

        Returns:
            :obj:`int`: Number of centroids
        """
        return self.__count_items("node_id", "nodes", "is_centroid=1")

    def count_nodes(self) -> int:
        """
        Returns the number of nodes in the model

        Returns:
            :obj:`int`: Number of nodes
        """
        return self.__count_items("node_id", "nodes", "node_id>=0")

    def extent(self):
        """Queries the extent of the network included in the model

        Returns:
            *model extent* (:obj:`Polygon`): Shapely polygon with the bounding box of the model network.
        """
        curr = self.conn.cursor()
        curr.execute('Select ST_asBinary(GetLayerExtent("Links"))')
        poly = shapely.wkb.loads(curr.fetchone()[0])
        return poly

    def convex_hull(self) -> Polygon:
        """ Queries the model for the convex hull of the entire network

        Returns:
            *model coverage* (:obj:`Polygon`): Shapely (Multi)polygon of the model network.
        """
        curr = self.conn.cursor()
        curr.execute('Select ST_asBinary("geometry") from Links where ST_Length("geometry") > 0;')
        links = [shapely.wkb.loads(x[0]) for x in curr.fetchall()]
        return unary_union(links).convex_hull

    def __count_items(self, field: str, table: str, condition: str) -> int:
        c = self.conn.cursor()
        c.execute(f"""select count({field}) from {table} where {condition};""")
        return c.fetchone()[0]
