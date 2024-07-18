# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""IDTReeS dataset."""

import glob
import os
from collections.abc import Callable
from typing import Any, cast, overload

import fiona
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import torch
from matplotlib.figure import Figure
from rasterio.enums import Resampling
from torch import Tensor
from torchvision.ops import clip_boxes_to_image, remove_small_boxes
from torchvision.utils import draw_bounding_boxes

from .errors import DatasetNotFoundError
from .geo import NonGeoDataset
from .utils import Path, download_url, extract_archive, lazy_import


class IDTReeS(NonGeoDataset):
    """IDTReeS dataset.

    The `IDTReeS <https://idtrees.org/competition/>`__
    dataset is a dataset for tree crown detection.

    Dataset features:

    * RGB Image, Canopy Height Model (CHM), Hyperspectral Image (HSI), LiDAR Point Cloud
    * Remote sensing and field data generated by the
      `National Ecological Observatory Network (NEON) <https://data.neonscience.org/>`_
    * 0.1 - 1m resolution imagery
    * Task 1 - object detection (tree crown delination)
    * Task 2 - object classification (species classification)
    * Train set contains 85 images
    * Test set (task 1) contains 153 images
    * Test set (task 2) contains 353 images and tree crown polygons

    Dataset format:

    * optical - three-channel RGB 200x200 geotiff
    * canopy height model - one-channel 20x20 geotiff
    * hyperspectral - 369-channel 20x20 geotiff
    * point cloud - Nx3 LAS file (.las), some files contain RGB colors per point
    * shapely files (.shp) containing polygons
    * csv file containing species labels and other metadata for each polygon

    Dataset classes:

    0. ACPE
    1. ACRU
    2. ACSA3
    3. AMLA
    4. BETUL
    5. CAGL8
    6. CATO6
    7. FAGR
    8. GOLA
    9. LITU
    10. LYLU3
    11. MAGNO
    12. NYBI
    13. NYSY
    14. OXYDE
    15. PEPA37
    16. PIEL
    17. PIPA2
    18. PINUS
    19. PITA
    20. PRSE2
    21. QUAL
    22. QUCO2
    23. QUGE2
    24. QUHE2
    25. QULA2
    26. QULA3
    27. QUMO4
    28. QUNI
    29. QURU
    30. QUERC
    31. ROPS
    32. TSCA

    If you use this dataset in your research, please cite the following paper:

    * https://doi.org/10.1101/2021.08.06.453503

    This dataset requires the following additional libraries to be installed:

       * `laspy <https://pypi.org/project/laspy/>`_ to read lidar point clouds
       * `pyvista <https://pypi.org/project/pyvista/>`_ to plot lidar point clouds

    .. versionadded:: 0.2
    """

    classes = {
        'ACPE': 'Acer pensylvanicum L.',
        'ACRU': 'Acer rubrum L.',
        'ACSA3': 'Acer saccharum Marshall',
        'AMLA': 'Amelanchier laevis Wiegand',
        'BETUL': 'Betula sp.',
        'CAGL8': 'Carya glabra (Mill.) Sweet',
        'CATO6': 'Carya tomentosa (Lam.) Nutt.',
        'FAGR': 'Fagus grandifolia Ehrh.',
        'GOLA': 'Gordonia lasianthus (L.) Ellis',
        'LITU': 'Liriodendron tulipifera L.',
        'LYLU3': 'Lyonia lucida (Lam.) K. Koch',
        'MAGNO': 'Magnolia sp.',
        'NYBI': 'Nyssa biflora Walter',
        'NYSY': 'Nyssa sylvatica Marshall',
        'OXYDE': 'Oxydendrum sp.',
        'PEPA37': 'Persea palustris (Raf.) Sarg.',
        'PIEL': 'Pinus elliottii Engelm.',
        'PIPA2': 'Pinus palustris Mill.',
        'PINUS': 'Pinus sp.',
        'PITA': 'Pinus taeda L.',
        'PRSE2': 'Prunus serotina Ehrh.',
        'QUAL': 'Quercus alba L.',
        'QUCO2': 'Quercus coccinea',
        'QUGE2': 'Quercus geminata Small',
        'QUHE2': 'Quercus hemisphaerica W. Bartram ex Willd.',
        'QULA2': 'Quercus laevis Walter',
        'QULA3': 'Quercus laurifolia Michx.',
        'QUMO4': 'Quercus montana Willd.',
        'QUNI': 'Quercus nigra L.',
        'QURU': 'Quercus rubra L.',
        'QUERC': 'Quercus sp.',
        'ROPS': 'Robinia pseudoacacia L.',
        'TSCA': 'Tsuga canadensis (L.) Carriere',
    }
    metadata = {
        'train': {
            'url': 'https://zenodo.org/record/3934932/files/IDTREES_competition_train_v2.zip?download=1',  # noqa: E501
            'md5': '5ddfa76240b4bb6b4a7861d1d31c299c',
            'filename': 'IDTREES_competition_train_v2.zip',
        },
        'test': {
            'url': 'https://zenodo.org/record/3934932/files/IDTREES_competition_test_v2.zip?download=1',  # noqa: E501
            'md5': 'b108931c84a70f2a38a8234290131c9b',
            'filename': 'IDTREES_competition_test_v2.zip',
        },
    }
    directories = {'train': ['train'], 'test': ['task1', 'task2']}
    image_size = (200, 200)

    def __init__(
        self,
        root: Path = 'data',
        split: str = 'train',
        task: str = 'task1',
        transforms: Callable[[dict[str, Tensor]], dict[str, Tensor]] | None = None,
        download: bool = False,
        checksum: bool = False,
    ) -> None:
        """Initialize a new IDTReeS dataset instance.

        Args:
            root: root directory where dataset can be found
            split: one of "train" or "test"
            task: 'task1' for detection, 'task2' for detection + classification
                (only relevant for split='test')
            transforms: a function/transform that takes input sample and its target as
                entry and returns a transformed version
            download: if True, download dataset and store it in the root directory
            checksum: if True, check the MD5 of the downloaded files (may be slow)

        Raises:
            DatasetNotFoundError: If dataset is not found and *download* is False.
            DependencyNotFoundError: If laspy is not installed.
        """
        lazy_import('laspy')

        assert split in ['train', 'test']
        assert task in ['task1', 'task2']

        self.root = root
        self.split = split
        self.task = task
        self.transforms = transforms
        self.download = download
        self.checksum = checksum
        self.class2idx = {c: i for i, c in enumerate(self.classes)}
        self.idx2class = {i: c for i, c in enumerate(self.classes)}
        self.num_classes = len(self.classes)
        self._verify()
        self.images, self.geometries, self.labels = self._load(root)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        """Return an index within the dataset.

        Args:
            index: index to return

        Returns:
            data and label at that index
        """
        path = self.images[index]
        image = self._load_image(path).to(torch.uint8)
        hsi = self._load_image(path.replace('RGB', 'HSI'))
        chm = self._load_image(path.replace('RGB', 'CHM'))
        las = self._load_las(path.replace('RGB', 'LAS').replace('.tif', '.las'))
        sample = {'image': image, 'hsi': hsi, 'chm': chm, 'las': las}

        if self.split == 'test':
            if self.task == 'task2':
                sample['boxes'] = self._load_boxes(path)
                h, w = sample['image'].shape[1:]
                sample['boxes'], _ = self._filter_boxes(
                    image_size=(h, w), min_size=1, boxes=sample['boxes'], labels=None
                )
        else:
            sample['boxes'] = self._load_boxes(path)
            sample['label'] = self._load_target(path)

            h, w = sample['image'].shape[1:]
            sample['boxes'], sample['label'] = self._filter_boxes(
                image_size=(h, w),
                min_size=1,
                boxes=sample['boxes'],
                labels=sample['label'],
            )

        if self.transforms is not None:
            sample = self.transforms(sample)

        return sample

    def __len__(self) -> int:
        """Return the number of data points in the dataset.

        Returns:
            length of the dataset
        """
        return len(self.images)

    def _load_image(self, path: Path) -> Tensor:
        """Load a tiff file.

        Args:
            path: path to .tif file

        Returns:
            the image
        """
        with rasterio.open(path) as f:
            array = f.read(out_shape=self.image_size, resampling=Resampling.bilinear)
        tensor = torch.from_numpy(array)
        return tensor

    def _load_las(self, path: Path) -> Tensor:
        """Load a single point cloud.

        Args:
            path: path to .las file

        Returns:
            the point cloud
        """
        laspy = lazy_import('laspy')
        las = laspy.read(path)
        array: np.typing.NDArray[np.int_] = np.stack([las.x, las.y, las.z], axis=0)
        tensor = torch.from_numpy(array)
        return tensor

    def _load_boxes(self, path: Path) -> Tensor:
        """Load object bounding boxes.

        Args:
            path: path to .tif file

        Returns:
            the bounding boxes
        """
        base_path = os.path.basename(path)
        geometries = cast(dict[int, dict[str, Any]], self.geometries)

        # Find object ids and geometries
        # The train set geometry->image mapping is contained
        # in the train/Field/itc_rsFile.csv file
        if self.split == 'train':
            indices = self.labels['rsFile'] == base_path
            ids = self.labels[indices]['id'].tolist()
            geoms = [geometries[i]['geometry']['coordinates'][0][:4] for i in ids]
        # The test set has no mapping csv. The mapping is inside of the geometry
        # properties i.e. geom["property"]["plotID"] contains the RGB image filename
        # Return all geometries with the matching RGB image filename of the sample
        else:
            ids = [
                k
                for k, v in geometries.items()
                if v['properties']['plotID'] == base_path
            ]
            geoms = [geometries[i]['geometry']['coordinates'][0][:4] for i in ids]

        # Convert to pixel coords
        boxes = []
        with rasterio.open(path) as f:
            for geom in geoms:
                coords = [f.index(x, y) for x, y in geom]
                xmin = min(coord[1] for coord in coords)
                xmax = max(coord[1] for coord in coords)
                ymin = min(coord[0] for coord in coords)
                ymax = max(coord[0] for coord in coords)
                boxes.append([xmin, ymin, xmax, ymax])

        tensor = torch.tensor(boxes)
        return tensor

    def _load_target(self, path: Path) -> Tensor:
        """Load target label for a single sample.

        Args:
            path: path to image

        Returns:
            the label
        """
        # Find indices for objects in the image
        base_path = os.path.basename(path)
        indices = self.labels['rsFile'] == base_path

        # Load object labels
        classes = self.labels[indices]['taxonID'].tolist()
        labels = [self.class2idx[c] for c in classes]
        tensor = torch.tensor(labels)
        return tensor

    def _load(
        self, root: Path
    ) -> tuple[list[str], dict[int, dict[str, Any]] | None, Any]:
        """Load files, geometries, and labels.

        Args:
            root: root directory

        Returns:
            the image path, geometries, and labels
        """
        if self.split == 'train':
            directory = os.path.join(root, self.directories[self.split][0])
            labels: pd.DataFrame = self._load_labels(directory)
            geoms = self._load_geometries(directory)
        else:
            directory = os.path.join(root, self.task)
            if self.task == 'task1':
                geoms = None
                labels = None
            else:
                geoms = self._load_geometries(directory)
                labels = None

        images = glob.glob(os.path.join(directory, 'RemoteSensing', 'RGB', '*.tif'))

        return images, geoms, labels

    def _load_labels(self, directory: Path) -> Any:
        """Load the csv files containing the labels.

        Args:
            directory: directory containing csv files

        Returns:
            a pandas DataFrame containing the labels for each image
        """
        path_mapping = os.path.join(directory, 'Field', 'itc_rsFile.csv')
        path_labels = os.path.join(directory, 'Field', 'train_data.csv')
        df_mapping = pd.read_csv(path_mapping)
        df_labels = pd.read_csv(path_labels)
        df_mapping = df_mapping.set_index('indvdID', drop=True)
        df_labels = df_labels.set_index('indvdID', drop=True)
        df = df_labels.join(df_mapping, on='indvdID')
        df = df.drop_duplicates()
        df.reset_index()
        return df

    def _load_geometries(self, directory: Path) -> dict[int, dict[str, Any]]:
        """Load the shape files containing the geometries.

        Args:
            directory: directory containing .shp files

        Returns:
            a dict containing the geometries for each object
        """
        filepaths = glob.glob(os.path.join(directory, 'ITC', '*.shp'))

        i = 0
        features: dict[int, dict[str, Any]] = {}
        for path in filepaths:
            with fiona.open(path) as src:
                for feature in src:
                    # The train set has a unique id for each geometry in the properties
                    if self.split == 'train':
                        features[feature['properties']['id']] = feature
                    # The test set has no unique id so create a dummy id
                    else:
                        features[i] = feature
                        i += 1
        return features

    @overload
    def _filter_boxes(
        self, image_size: tuple[int, int], min_size: int, boxes: Tensor, labels: Tensor
    ) -> tuple[Tensor, Tensor]: ...

    @overload
    def _filter_boxes(
        self, image_size: tuple[int, int], min_size: int, boxes: Tensor, labels: None
    ) -> tuple[Tensor, None]: ...

    def _filter_boxes(
        self,
        image_size: tuple[int, int],
        min_size: int,
        boxes: Tensor,
        labels: Tensor | None,
    ) -> tuple[Tensor, Tensor | None]:
        """Clip boxes to image size and filter boxes with sides less than ``min_size``.

        Args:
            image_size: tuple of (height, width) of image
            min_size: filter boxes that have any side less than min_size
            boxes: [N, 4] shape tensor of xyxy bounding box coordinates
            labels: (Optional) [N,] shape tensor of bounding box labels

        Returns:
            a tuple of filtered boxes and labels
        """
        boxes = clip_boxes_to_image(boxes=boxes, size=image_size)
        indices = remove_small_boxes(boxes=boxes, min_size=min_size)

        boxes = boxes[indices]
        if labels is not None:
            labels = labels[indices]

        return boxes, labels

    def _verify(self) -> None:
        """Verify the integrity of the dataset."""
        url = self.metadata[self.split]['url']
        md5 = self.metadata[self.split]['md5']
        filename = self.metadata[self.split]['filename']
        directories = self.directories[self.split]

        # Check if the files already exist
        exists = [
            os.path.exists(os.path.join(self.root, directory))
            for directory in directories
        ]
        if all(exists):
            return

        # Check if zip file already exists (if so then extract)
        filepath = os.path.join(self.root, filename)
        if os.path.exists(filepath):
            extract_archive(filepath)
            return

        # Check if the user requested to download the dataset
        if not self.download:
            raise DatasetNotFoundError(self)

        # Download and extract the dataset
        download_url(
            url, self.root, filename=filename, md5=md5 if self.checksum else None
        )
        filepath = os.path.join(self.root, filename)
        extract_archive(filepath)

    def plot(
        self,
        sample: dict[str, Tensor],
        show_titles: bool = True,
        suptitle: str | None = None,
        hsi_indices: tuple[int, int, int] = (0, 1, 2),
    ) -> Figure:
        """Plot a sample from the dataset.

        Args:
            sample: a sample returned by :meth:`__getitem__`
            show_titles: flag indicating whether to show titles above each panel
            suptitle: optional string to use as a suptitle
            hsi_indices: tuple of indices to create HSI false color image

        Returns:
            a matplotlib Figure with the rendered sample
        """
        assert len(hsi_indices) == 3

        def normalize(x: Tensor) -> Tensor:
            return (x - x.min()) / (x.max() - x.min())

        ncols = 3

        hsi = normalize(sample['hsi'][hsi_indices, :, :]).permute((1, 2, 0)).numpy()
        chm = normalize(sample['chm']).permute((1, 2, 0)).numpy()

        if 'boxes' in sample and len(sample['boxes']):
            labels = (
                [self.idx2class[int(i)] for i in sample['label']]
                if 'label' in sample
                else None
            )
            image = draw_bounding_boxes(
                image=sample['image'], boxes=sample['boxes'], labels=labels
            )
            image = image.permute((1, 2, 0)).numpy()
        else:
            image = sample['image'].permute((1, 2, 0)).numpy()

        if 'prediction_boxes' in sample and len(sample['prediction_boxes']):
            ncols += 1
            labels = (
                [self.idx2class[int(i)] for i in sample['prediction_label']]
                if 'prediction_label' in sample
                else None
            )
            preds = draw_bounding_boxes(
                image=sample['image'], boxes=sample['prediction_boxes'], labels=labels
            )
            preds = preds.permute((1, 2, 0)).numpy()

        fig, axs = plt.subplots(ncols=ncols, figsize=(ncols * 10, 10))
        axs[0].imshow(image)
        axs[0].axis('off')
        axs[1].imshow(hsi)
        axs[1].axis('off')
        axs[2].imshow(chm)
        axs[2].axis('off')
        if ncols > 3:
            axs[3].imshow(preds)
            axs[3].axis('off')

        if show_titles:
            axs[0].set_title('Ground Truth')
            axs[1].set_title('Hyperspectral False Color Image')
            axs[2].set_title('Canopy Height Model')
            if ncols > 3:
                axs[3].set_title('Predictions')

        if suptitle is not None:
            plt.suptitle(suptitle)

        return fig

    def plot_las(self, index: int) -> 'pyvista.Plotter':  # type: ignore[name-defined] # noqa: F821
        """Plot a sample point cloud at the index.

        Args:
            index: index to plot

        Returns:
            pyvista.PolyData object. Run pyvista.plot(point_cloud, ...) to display

        Raises:
            DependencyNotFoundError: If laspy or pyvista are not installed.

        .. versionchanged:: 0.4
           Ported from Open3D to PyVista, *colormap* parameter removed.
        """
        laspy = lazy_import('laspy')
        pyvista = lazy_import('pyvista')
        path = self.images[index]
        path = path.replace('RGB', 'LAS').replace('.tif', '.las')
        las = laspy.read(path)
        points: np.typing.NDArray[np.int_] = np.stack(
            [las.x, las.y, las.z], axis=0
        ).transpose((1, 0))
        point_cloud = pyvista.PolyData(points)

        # Some point cloud files have no color->points mapping
        if hasattr(las, 'red'):
            colors = np.stack([las.red, las.green, las.blue], axis=0)
            colors = colors.transpose((1, 0)) / np.iinfo(np.uint16).max
            point_cloud['colors'] = colors

        return point_cloud
